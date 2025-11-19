from flask import Flask, request, jsonify
from flask_cors import CORS
from instagrapi import Client
from instagrapi.exceptions import LoginRequired, UserNotFound, PleaseWaitFewMinutes
import os
from dotenv import load_dotenv
import json
from typing import Optional, Dict, List
import re
import time
import logging
from pathlib import Path
import csv
import difflib

# Try to import OpenAI, but make it optional
try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

load_dotenv()

app = Flask(__name__)
CORS(app)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global client instance
cl = None

def login_client(client: Client, force: bool = False, max_retries: int = 3) -> bool:
    """Login to Instagram with retry logic"""
    username = os.getenv('INSTAGRAM_USERNAME')
    password = os.getenv('INSTAGRAM_PASSWORD')
    
    if not username or not password:
        raise ValueError("Instagram credentials not found in environment variables")
    
    session_file = 'session.json'
    
    # Try to load session if exists and not forcing re-login
    if not force and os.path.exists(session_file):
        try:
            with open(session_file, 'r') as f:
                session_data = json.load(f)
                client.set_settings(session_data)
                # Don't call login() when loading session - just verify it works
                # by trying a lightweight operation
                try:
                    # Try to get current user to verify session is valid
                    client.account_info()
                    print("✅ Loaded existing session (verified)")
                    return True
                except LoginRequired:
                    # Session is invalid, will fall through to login
                    print("🔄 Session expired, re-authenticating...")
                    pass
        except Exception as e:
            print(f"⚠️  Could not load session: {e}")
            # Fall through to login
    
    # Login (either new or re-authentication) with retry logic
    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            client.login(username, password)
            print("✅ Successfully logged in to Instagram")
            
            # Save session
            try:
                settings = client.get_settings()
                with open(session_file, 'w') as f:
                    json.dump(settings, f)
                print("💾 Session saved")
            except Exception as e:
                print(f"⚠️  Could not save session: {e}")
            
            return True
        except Exception as e:
            last_error = e
            error_str = str(e).lower()
            
            # Determine wait time based on error type
            if 'challenge' in error_str or '500' in error_str:
                # Challenge or server errors: wait 5-15 minutes
                wait_minutes = 10 if attempt == 1 else 15
                wait_seconds = wait_minutes * 60
                print(f"❌ Login failed (attempt {attempt}/{max_retries}): {e}")
                if attempt < max_retries:
                    print(f"⏳ Waiting {wait_minutes} minutes before retry (Instagram challenge/rate limit)...")
                    time.sleep(wait_seconds)
                else:
                    print(f"❌ Max retries reached. Please wait {wait_minutes} minutes and try again.")
            elif 'rate limit' in error_str or 'too many' in error_str:
                # Rate limit: wait 15-30 minutes
                wait_minutes = 20 if attempt == 1 else 30
                wait_seconds = wait_minutes * 60
                print(f"❌ Login failed (attempt {attempt}/{max_retries}): Rate limited")
                if attempt < max_retries:
                    print(f"⏳ Waiting {wait_minutes} minutes before retry (Instagram rate limit)...")
                    time.sleep(wait_seconds)
                else:
                    print(f"❌ Max retries reached. Please wait {wait_minutes} minutes and try again.")
            else:
                # Other errors: wait 1-3 minutes
                wait_minutes = 2 if attempt == 1 else 3
                wait_seconds = wait_minutes * 60
                print(f"❌ Login failed (attempt {attempt}/{max_retries}): {e}")
                if attempt < max_retries:
                    print(f"⏳ Waiting {wait_minutes} minutes before retry...")
                    time.sleep(wait_seconds)
    
    # All retries failed
    print(f"❌ Login failed after {max_retries} attempts: {last_error}")
    raise last_error

def get_client(force_login: bool = False) -> Client:
    """Get or create Instagram client instance"""
    global cl
    
    # Create new client if needed or if forcing re-login
    if cl is None or force_login:
        if cl is None:
            cl = Client()
        login_client(cl, force=force_login)
    else:
        # Verify existing client session is still valid
        try:
            cl.account_info()
        except LoginRequired:
            # Session expired, re-authenticate
            print("🔄 Existing session expired, re-authenticating...")
            login_client(cl, force=True)
    
    return cl

def ensure_logged_in(func):
    """Decorator to ensure client is logged in, re-authenticate if needed"""
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except LoginRequired:
            print("🔄 Session expired, re-authenticating...")
            global cl
            cl = None  # Reset client to force re-login
            get_client(force_login=True)
            return func(*args, **kwargs)  # Retry once
    return wrapper

def format_phone_with_country_code(phone: str, country_code: Optional[str] = None) -> str:
    """Format phone number with country code (+ prefix)"""
    if not phone:
        return phone
    
    # Remove all non-digit characters except +
    cleaned = re.sub(r'[^\d+]', '', str(phone))
    
    # If already has country code (starts with +), return as is
    if cleaned.startswith('+'):
        return cleaned
    
    # If country code is provided, use it
    if country_code:
        # Remove + if present in country_code
        cc = str(country_code).replace('+', '').strip()
        # Remove leading zeros
        cc = cc.lstrip('0')
        return f"+{cc}{cleaned}"
    
    # Detect US/Canada numbers (10 digits, or 11 digits starting with 1)
    digits_only = re.sub(r'\D', '', cleaned)
    
    # If 11 digits and starts with 1, it's US/Canada with country code
    if len(digits_only) == 11 and digits_only.startswith('1'):
        return f"+{digits_only}"
    
    # If 10 digits, assume US/Canada and add +1
    if len(digits_only) == 10:
        # Check if it's a US toll-free or common US number pattern
        # US area codes start with 2-9, toll-free: 800, 888, 877, 866, 855, 844, 833
        first_three = digits_only[:3]
        if (digits_only[0] in '23456789' or 
            first_three in ['800', '888', '877', '866', '855', '844', '833']):
            return f"+1{digits_only}"
    
    # For other lengths, return as is (might be international without +)
    # Or could add logic to detect other countries
    return cleaned

def extract_contact_info(bio: str, user_info: Dict, external_url: Optional[str] = None) -> Dict[str, Optional[str]]:
    """Extract contact information from bio, external URL, and user info"""
    contact_info = {
        'facebook_page': None,
        'website': None,
        'business_email': None,
        'business_phone': None,
        'email': None,  # Add email field for emails extracted from bio
    }
    
    # Combine bio and external_url for searching
    search_text = bio
    if external_url:
        search_text += ' ' + external_url
    
    # Extract email addresses from bio and external_url
    # Pattern matches: user@domain.com, user@domain.com.mx, etc.
    email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}(?:\.[A-Z|a-z]{2,})?\b'
    emails = re.findall(email_pattern, search_text, re.IGNORECASE)
    if emails:
        # Filter out common false positives (like @instagram, @facebook in text)
        valid_emails = [email for email in emails if not any(
            domain in email.lower() for domain in ['instagram.com', 'facebook.com', 'fb.com', 'twitter.com', 'x.com']
        )]
        if valid_emails:
            contact_info['email'] = valid_emails[0]
    
    # Extract Facebook page links
    facebook_patterns = [
        r'https?://(?:www\.)?(?:facebook|fb)\.com/[a-zA-Z0-9.]+',
        r'https?://(?:www\.)?(?:facebook|fb)\.com/[a-zA-Z0-9./-]+',
        r'facebook\.com/[a-zA-Z0-9.]+',
        r'fb\.com/[a-zA-Z0-9.]+',
        r'@[a-zA-Z0-9.]+.*facebook',
        r'facebook.*@[a-zA-Z0-9.]+',
    ]
    
    facebook_links = []
    for pattern in facebook_patterns:
        found = re.findall(pattern, search_text, re.IGNORECASE)
        facebook_links.extend(found)
    
    if facebook_links:
        # Clean and format Facebook URLs
        fb_link = facebook_links[0]
        # If it doesn't start with http, add it
        if not fb_link.startswith('http'):
            fb_link = 'https://' + fb_link
        # Ensure it's a full URL
        if 'facebook.com' not in fb_link and 'fb.com' not in fb_link:
            if fb_link.startswith('@'):
                fb_link = 'https://facebook.com/' + fb_link[1:]
            else:
                fb_link = 'https://facebook.com/' + fb_link
        contact_info['facebook_page'] = fb_link
    
    # Extract other website/URL from bio (non-Facebook)
    url_pattern = r'https?://(?:www\.)?[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}(?:/[^\s]*)?'
    urls = re.findall(url_pattern, search_text)
    if urls:
        # Filter out Facebook URLs and Instagram URLs
        non_social_urls = [url for url in urls if 'facebook' not in url.lower() and 'fb.com' not in url.lower() and 'instagram.com' not in url.lower()]
        if non_social_urls:
            contact_info['website'] = non_social_urls[0]
        elif urls:
            contact_info['website'] = urls[0]
    
    # Check for business contact info
    # Handle case where user_info might not be a dict
    if isinstance(user_info, dict):
        # Check if it's a business account
        is_business = user_info.get('is_business', False) or user_info.get('is_business_account', False)
        
        if is_business:
            # Try multiple ways to get business contact info
            business_contact = user_info.get('business_contact_method', {})
            if not business_contact and isinstance(user_info.get('business_contact_method'), dict):
                business_contact = user_info.get('business_contact_method')
            
                # Also check direct fields
            if isinstance(business_contact, dict):
                business_email = business_contact.get('email') or business_contact.get('email_address')
                business_phone = (business_contact.get('phone_number') or 
                                 business_contact.get('phone') or 
                                 business_contact.get('contact_phone_number') or
                                 business_contact.get('public_phone_number'))
                business_country_code = (business_contact.get('country_code') or 
                                       business_contact.get('phone_country_code'))
                
                # Only set business contact info if it's from public business settings
                if business_email:
                    contact_info['business_email'] = business_email
                
                if business_phone:
                    contact_info['business_phone'] = format_phone_with_country_code(business_phone, business_country_code)
            
            # Also check for direct business fields in user_info (public business info)
            direct_business_email = user_info.get('public_email') or user_info.get('business_email')
            if direct_business_email:
                contact_info['business_email'] = direct_business_email
            
            # Also check for direct business phone in user_info
            if not contact_info['business_phone']:
                direct_business_phone = (user_info.get('business_phone_number') or 
                                       user_info.get('public_phone_number') or 
                                       user_info.get('contact_phone_number'))
                direct_country_code = (user_info.get('phone_country_code') or 
                                     user_info.get('country_code'))
                if direct_business_phone:
                    contact_info['business_phone'] = format_phone_with_country_code(direct_business_phone, direct_country_code)
    
    return contact_info

# Cache for categories
CATEGORIES_CACHE = []

def load_categories():
    """Load categories from CSV file"""
    global CATEGORIES_CACHE
    if CATEGORIES_CACHE:
        return CATEGORIES_CACHE
        
    try:
        # Look for CSV file in docs directory
        csv_path = Path('docs/instagram_categories.csv')
        if not csv_path.exists():
            # Try relative to script location
            script_dir = Path(__file__).parent.parent
            csv_path = script_dir / 'docs' / 'instagram_categories.csv'
            
        if csv_path.exists():
            with open(csv_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                CATEGORIES_CACHE = [row['category'] for row in reader if row.get('category')]
            logger.info(f"Loaded {len(CATEGORIES_CACHE)} categories from CSV")
        else:
            logger.warning("Categories CSV not found")
            
    except Exception as e:
        logger.error(f"Error loading categories: {e}")
        
    return CATEGORIES_CACHE

def find_closest_category(category_guess: str) -> Optional[str]:
    """Find closest matching category from the allowed list"""
    categories = load_categories()
    if not categories or not category_guess:
        return None
    
    category_guess_lower = category_guess.lower().strip()
        
    # Exact match (case-insensitive)
    for cat in categories:
        if cat.lower() == category_guess_lower:
            return cat
            
    # Check if guess is contained in category or vice versa (for partial matches)
    for cat in categories:
        cat_lower = cat.lower()
        if category_guess_lower in cat_lower or cat_lower in category_guess_lower:
            # Prefer exact or very close matches
            if len(category_guess_lower) > 3 and len(cat_lower) > 3:
                return cat
            
    # Fuzzy match with better cutoff
    matches = difflib.get_close_matches(category_guess, categories, n=3, cutoff=0.55)
    if matches:
        # Prefer matches that are common words
        for match in matches:
            if match.lower() in ['musician', 'athlete', 'artist', 'actor', 'chef', 'coach', 'photographer']:
                return match
        return matches[0]
        
    return None

# Cache for AI results to avoid re-generating for same user in same session
AI_ENRICHMENT_CACHE = {}

def enrich_profile_with_ai(user_data: Dict) -> Dict:
    """
    Use LLM to enrich user profile with description, and optionally location/category if missing.
    """
    if not OPENAI_AVAILABLE:
        logger.warning("OpenAI not available, skipping AI enrichment")
        return {}
        
    username = user_data.get('username')
    if not username:
        return {}
        
    # Check cache
    if username in AI_ENRICHMENT_CACHE:
        return AI_ENRICHMENT_CACHE[username]

    # Prepare prompt inputs
    existing_category = user_data.get('category') or user_data.get('business_category_name')
    existing_location = user_data.get('city_name') or user_data.get('address_street')
    
    needs_category = not existing_category
    needs_location = not existing_location
    
    try:
        api_key = os.getenv('OPENAI_API_KEY')
        if not api_key:
            logger.warning("OPENAI_API_KEY not set, skipping AI enrichment")
            return {}
            
        client = OpenAI(api_key=api_key)
        
        # Get all categories for better matching
        all_categories = load_categories()
        
        prompt_text = f"""Analyze this Instagram profile and provide missing details.

Profile Data:
Username: {username}
Full Name: {user_data.get('full_name', '')}
Bio: {user_data.get('biography', '') or user_data.get('bio', '')}
External URL: {user_data.get('external_url', '')}
Media Count: {user_data.get('media_count', 0)}
Follower Count: {user_data.get('follower_count', 0)}

Requirements:
1. Generate a 4-sentence professional description/summary of the user/business based on their bio and details.

2. LOCATION INFERENCE (if location is missing):
   - FIRST PRIORITY: Infer their country of residence/where they currently live based on bio, mentions, or known facts
   - SECOND PRIORITY: If residence unknown, use their nationality/country of origin
   - Format: "City, Country" or "Country" if city unknown
   - ONLY return null if absolutely no geographic information can be inferred
   - For public figures (athletes, musicians, etc.), use your knowledge of where they live

3. CATEGORY INFERENCE (if category is missing):
   - Choose the MOST APPROPRIATE category from the provided list
   - IMPORTANT: Do NOT choose "Album" for musicians - use "Musician", "Musician/Band", "Musical Instrument", etc.
   - For athletes, use "Athlete" not other categories
   - Match the person's primary profession/role, not secondary attributes
   - Categories are case-sensitive - match EXACTLY from the list below

ALL Valid Categories ({len(all_categories)} total):
{', '.join(all_categories)}

Return JSON format:
{{
    "description": "4 sentences description...",
    "location_guess": "City, Country" or "Country" or null,
    "category_guess": "Exact category name from list" or null
}}
"""
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",  # Using a valid model name instead of gpt-5.1-nano which doesn't exist
            messages=[
                {"role": "system", "content": "You are a helpful assistant that analyzes Instagram profiles. Always return valid JSON."},
                {"role": "user", "content": prompt_text}
            ],
            temperature=0,
            response_format={"type": "json_object"}
        )
        
        result_text = response.choices[0].message.content
        result = json.loads(result_text)
        
        enrichment = {
            "ai_description": result.get("description")
        }
        
        # Handle location - check for null strings
        location_val = result.get("location_guess")
        if needs_location and location_val:
            location_val_str = str(location_val).strip()
            # Check if it's not a null-like value
            if location_val_str.lower() not in ['null', 'none', 'n/a', '']:
                enrichment["ai_location"] = location_val_str
                
        # Handle category - validate against list with better matching
        category_val = result.get("category_guess")
        if needs_category and category_val:
            category_val_str = str(category_val).strip()
            # Check if it's not a null-like value
            if category_val_str.lower() not in ['null', 'none', 'n/a', '']:
                # First try exact match
                matched_cat = find_closest_category(category_val_str)
                if matched_cat:
                    enrichment["ai_category"] = matched_cat
                else:
                    # Try with more lenient fuzzy matching
                    categories = load_categories()
                    matches = difflib.get_close_matches(category_val_str, categories, n=3, cutoff=0.5)
                    if matches:
                        enrichment["ai_category"] = matches[0]
                        logger.info(f"Matched category '{category_val_str}' to '{matches[0]}' for {username}")
                    else:
                        logger.warning(f"Could not match category '{category_val_str}' for {username}")
                
        # Update cache
        AI_ENRICHMENT_CACHE[username] = enrichment
        logger.info(f"AI Enrichment success for {username}: {enrichment}")
        return enrichment
        
    except Exception as e:
        logger.error(f"AI Enrichment failed for {username}: {e}")
        return {}

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({'status': 'ok'})

@app.route('/login', methods=['POST'])
def login():
    """Login to Instagram"""
    global cl
    try:
        data = request.json
        username = data.get('username') or os.getenv('INSTAGRAM_USERNAME')
        password = data.get('password') or os.getenv('INSTAGRAM_PASSWORD')
        
        if not username or not password:
            return jsonify({'error': 'Username and password required'}), 400
        
        cl = Client()
        cl.login(username, password)
        
        # Save session
        try:
            settings = cl.get_settings()
            with open('session.json', 'w') as f:
                json.dump(settings, f)
        except Exception as e:
            print(f"Could not save session: {e}")
        
        return jsonify({'status': 'success', 'message': 'Logged in successfully'})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/followers', methods=['POST'])
def get_followers():
    """Get followers of a target Instagram account"""
    global cl
    try:
        client = get_client()
        data = request.json or {}
        
        target_username = data.get('username')
        target_user_id = data.get('user_id')
        limit = data.get('limit', 20)
        
        if not target_username and not target_user_id:
            return jsonify({'error': 'Either username or user_id is required'}), 400
        
        # Get user ID if username provided
        if target_username:
            try:
                user_id = client.user_id_from_username(target_username)
                logger.info(f"[RAW API] user_id_from_username('{target_username}') = {user_id}")
            except LoginRequired:
                # Re-authenticate and retry
                print("🔄 Session expired during username lookup, re-authenticating...")
                cl = None
                client = get_client(force_login=True)
                try:
                    user_id = client.user_id_from_username(target_username)
                    logger.info(f"[RAW API] user_id_from_username('{target_username}') = {user_id} [retry]")
                except UserNotFound:
                    return jsonify({'error': f'User @{target_username} not found'}), 404
            except UserNotFound:
                return jsonify({'error': f'User @{target_username} not found'}), 404
        else:
            user_id = target_user_id
        
        # Get followers
        try:
            followers = client.user_followers(user_id, amount=limit)
            logger.info(f"[RAW API] user_followers(user_id='{user_id}', amount={limit})")
            logger.info(f"[RAW API] Raw followers data: {json.dumps(followers, default=str, indent=2)}")
        except LoginRequired:
            # Try to re-authenticate and retry once
            print("🔄 Session expired, attempting re-authentication...")
            try:
                cl = None  # Reset client
                client = get_client(force_login=True)
                followers = client.user_followers(user_id, amount=limit)
                logger.info(f"[RAW API] user_followers(user_id='{user_id}', amount={limit}) [retry]")
                logger.info(f"[RAW API] Raw followers data: {json.dumps(followers, default=str, indent=2)}")
            except Exception as retry_error:
                return jsonify({'error': f'Session expired and re-authentication failed: {str(retry_error)}'}), 401
        except PleaseWaitFewMinutes as e:
            return jsonify({'error': f'Rate limited: {str(e)}'}), 429
        except Exception as e:
            return jsonify({'error': f'Error fetching followers: {str(e)}'}), 500
        
        # Get detailed info for each follower
        followers_data = []
        for idx, (user_id_str, user_info) in enumerate(list(followers.items())[:limit], 1):
            # Add small delay between requests to avoid rate limiting (except for first request)
            if idx > 1:
                time.sleep(0.5)  # 500ms delay between requests
            try:
                # Get full user info
                try:
                    user_details = client.user_info(user_id_str)
                    # Log raw user info data
                    try:
                        raw_user_dict = user_details.dict() if hasattr(user_details, 'dict') else {}
                        logger.info(f"[RAW API] user_info(user_id='{user_id_str}')")
                        logger.info(f"[RAW API] Raw user info data: {json.dumps(raw_user_dict, default=str, indent=2)}")
                    except Exception as log_error:
                        logger.warning(f"[RAW API] Could not serialize user_info for logging: {log_error}")
                        logger.info(f"[RAW API] user_info(user_id='{user_id_str}') = {type(user_details).__name__}")
                except LoginRequired:
                    # Re-authenticate and retry
                    print(f"🔄 Session expired while fetching user {user_id_str}, re-authenticating...")
                    cl = None
                    client = get_client(force_login=True)
                    user_details = client.user_info(user_id_str)
                    # Log raw user info data
                    try:
                        raw_user_dict = user_details.dict() if hasattr(user_details, 'dict') else {}
                        logger.info(f"[RAW API] user_info(user_id='{user_id_str}') [retry]")
                        logger.info(f"[RAW API] Raw user info data: {json.dumps(raw_user_dict, default=str, indent=2)}")
                    except Exception as log_error:
                        logger.warning(f"[RAW API] Could not serialize user_info for logging: {log_error}")
                        logger.info(f"[RAW API] user_info(user_id='{user_id_str}') = {type(user_details).__name__} [retry]")
                except Exception as e:
                    # If we can't get detailed info, use basic info from user_info
                    print(f"⚠️  Could not get detailed info for user {user_id_str}: {e}")
                    # user_info is a UserShort object, access attributes directly
                    try:
                        username = user_info.username if hasattr(user_info, 'username') else str(user_id_str)
                        full_name = user_info.full_name if hasattr(user_info, 'full_name') else ''
                    except:
                        username = str(user_id_str)
                        full_name = ''
                    
                    followers_data.append({
                        'username': username,
                        'full_name': full_name,
                        'error': f'Could not fetch detailed info: {str(e)}',
                        'bio': '',
                        'is_verified': False,
                        'is_private': False,
                        'follower_count': 0,
                        'following_count': 0,
                        'post_count': 0,
                        'email': None,
                        'phone': None,
                        'website': None,
                        'business_email': None,
                        'business_phone': None,
                        'account_type': 'personal'
                    })
                    continue
                
                # Extract contact info from bio and external URL
                bio = user_details.biography or ''
                external_url = getattr(user_details, 'external_url', None) or ''
                
                # Safely convert user_details to dict and extract business info
                try:
                    user_dict = user_details.dict() if hasattr(user_details, 'dict') else {}
                except:
                    user_dict = {}
                
                # Also try to get business contact info directly from user_details object
                try:
                    if hasattr(user_details, 'is_business') and user_details.is_business:
                        if hasattr(user_details, 'business_contact_method'):
                            business_method = user_details.business_contact_method
                            if business_method:
                                if 'business_contact_method' not in user_dict:
                                    user_dict['business_contact_method'] = {}
                                
                                # Check for email
                                if hasattr(business_method, 'email') and business_method.email:
                                    user_dict['business_contact_method']['email'] = business_method.email
                                
                                # Check for phone number - try multiple attribute names
                                phone_number = None
                                if hasattr(business_method, 'phone_number') and business_method.phone_number:
                                    phone_number = business_method.phone_number
                                elif hasattr(business_method, 'phone') and business_method.phone:
                                    phone_number = business_method.phone
                                elif hasattr(business_method, 'contact_phone_number') and business_method.contact_phone_number:
                                    phone_number = business_method.contact_phone_number
                                elif hasattr(business_method, 'public_phone_number') and business_method.public_phone_number:
                                    phone_number = business_method.public_phone_number
                                
                                # Also check for country code
                                country_code = None
                                if hasattr(business_method, 'country_code') and business_method.country_code:
                                    country_code = business_method.country_code
                                elif hasattr(business_method, 'phone_country_code') and business_method.phone_country_code:
                                    country_code = business_method.phone_country_code
                                
                                if phone_number:
                                    formatted_phone = format_phone_with_country_code(phone_number, country_code)
                                    user_dict['business_contact_method']['phone_number'] = formatted_phone
                        
                        # Also check for phone number directly on user_details object
                        if not user_dict.get('business_contact_method', {}).get('phone_number'):
                            direct_phone = None
                            direct_country_code = None
                            if hasattr(user_details, 'business_phone_number') and user_details.business_phone_number:
                                direct_phone = user_details.business_phone_number
                            elif hasattr(user_details, 'public_phone_number') and user_details.public_phone_number:
                                direct_phone = user_details.public_phone_number
                            elif hasattr(user_details, 'contact_phone_number') and user_details.contact_phone_number:
                                direct_phone = user_details.contact_phone_number
                            
                            # Check for country code on user_details
                            if hasattr(user_details, 'phone_country_code') and user_details.phone_country_code:
                                direct_country_code = user_details.phone_country_code
                            elif hasattr(user_details, 'country_code') and user_details.country_code:
                                direct_country_code = user_details.country_code
                            
                            if direct_phone:
                                if 'business_contact_method' not in user_dict:
                                    user_dict['business_contact_method'] = {}
                                formatted_phone = format_phone_with_country_code(direct_phone, direct_country_code)
                                user_dict['business_contact_method']['phone_number'] = formatted_phone
                except Exception as e:
                    pass  # Silently fail for followers to avoid spam
                
                contact_info = extract_contact_info(bio, user_dict, external_url)
                
                # Determine account type for follower
                follower_account_type_str = 'personal'
                follower_is_business = False
                follower_is_creator = False
                
                # Check for business account
                if hasattr(user_details, 'is_business') and user_details.is_business:
                    follower_is_business = True
                    follower_account_type_str = 'business'
                elif hasattr(user_details, 'is_business_account') and user_details.is_business_account:
                    follower_is_business = True
                    follower_account_type_str = 'business'
                elif user_dict.get('is_business') or user_dict.get('is_business_account'):
                    follower_is_business = True
                    follower_account_type_str = 'business'
                
                # Check for creator account
                if hasattr(user_details, 'is_creator') and user_details.is_creator:
                    follower_is_creator = True
                    follower_account_type_str = 'creator'
                elif hasattr(user_details, 'is_creator_account') and user_details.is_creator_account:
                    follower_is_creator = True
                    follower_account_type_str = 'creator'
                elif user_dict.get('is_creator') or user_dict.get('is_creator_account'):
                    follower_is_creator = True
                    follower_account_type_str = 'creator'
                
                follower_data = {
                    'username': user_details.username,
                    'full_name': user_details.full_name,
                    'bio': bio,
                    'is_verified': user_details.is_verified,
                    'is_private': user_details.is_private,
                    'follower_count': user_details.follower_count,
                    'following_count': user_details.following_count,
                    'post_count': user_details.media_count,
                    'external_url': user_details.external_url,
                    'account_type': follower_account_type_str,
                    **contact_info
                }
                
                followers_data.append(follower_data)
            except Exception as e:
                print(f"❌ Error getting info for user {user_id_str}: {e}")
                # Add basic info if detailed fetch fails
                # user_info might be a UserShort object or dict
                try:
                    if hasattr(user_info, 'username'):
                        username = user_info.username
                    elif isinstance(user_info, dict):
                        username = user_info.get('username', 'unknown')
                    else:
                        username = 'unknown'
                except:
                    username = 'unknown'
                
                followers_data.append({
                    'username': username,
                    'error': str(e),
                    'bio': '',
                    'is_verified': False,
                    'is_private': False,
                    'follower_count': 0,
                    'following_count': 0,
                    'post_count': 0,
                    'email': None,
                    'phone': None,
                    'website': None,
                    'business_email': None,
                    'business_phone': None,
                    'account_type': 'personal'
                })
        
        return jsonify({
            'status': 'success',
            'target_user_id': str(user_id),
            'target_username': target_username,
            'count': len(followers_data),
            'followers': followers_data
        })
    
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/user-info', methods=['POST'])
def get_user_info():
    """Get information about a specific user"""
    global cl
    try:
        client = get_client()
        data = request.json or {}
        
        target_username = data.get('username')
        target_user_id = data.get('user_id')
        
        if not target_username and not target_user_id:
            return jsonify({'error': 'Either username or user_id is required'}), 400
        
        # Get user ID if username provided
        if target_username:
            try:
                user_id = client.user_id_from_username(target_username)
                logger.info(f"[RAW API] user_id_from_username('{target_username}') = {user_id}")
            except LoginRequired:
                # Re-authenticate and retry
                print("🔄 Session expired during username lookup, re-authenticating...")
                cl = None
                client = get_client(force_login=True)
                try:
                    user_id = client.user_id_from_username(target_username)
                    logger.info(f"[RAW API] user_id_from_username('{target_username}') = {user_id} [retry]")
                except UserNotFound:
                    return jsonify({'error': f'User @{target_username} not found'}), 404
            except UserNotFound:
                return jsonify({'error': f'User @{target_username} not found'}), 404
        else:
            user_id = target_user_id
        
        # Get user details
        # Note: This works for ANY public Instagram user, not just followers
        try:
            user_details = client.user_info(user_id)
            # Log raw user info data
            try:
                raw_user_dict = user_details.dict() if hasattr(user_details, 'dict') else {}
                logger.info(f"[RAW API] user_info(user_id='{user_id}')")
                logger.info(f"[RAW API] Raw user info data: {json.dumps(raw_user_dict, default=str, indent=2)}")
            except Exception as log_error:
                logger.warning(f"[RAW API] Could not serialize user_info for logging: {log_error}")
                logger.info(f"[RAW API] user_info(user_id='{user_id}') = {type(user_details).__name__}")
        except LoginRequired:
            # Try to re-authenticate and retry once
            print("🔄 Session expired, attempting re-authentication...")
            try:
                cl = None  # Reset client
                client = get_client(force_login=True)
                user_details = client.user_info(user_id)
                # Log raw user info data
                try:
                    raw_user_dict = user_details.dict() if hasattr(user_details, 'dict') else {}
                    logger.info(f"[RAW API] user_info(user_id='{user_id}') [retry]")
                    logger.info(f"[RAW API] Raw user info data: {json.dumps(raw_user_dict, default=str, indent=2)}")
                except Exception as log_error:
                    logger.warning(f"[RAW API] Could not serialize user_info for logging: {log_error}")
                    logger.info(f"[RAW API] user_info(user_id='{user_id}') = {type(user_details).__name__} [retry]")
            except Exception as retry_error:
                return jsonify({'error': f'Session expired and re-authentication failed: {str(retry_error)}'}), 401
        except Exception as e:
            error_msg = str(e).lower()
            if 'private' in error_msg or 'not authorized' in error_msg:
                return jsonify({
                    'error': f'Cannot access user @{target_username or user_id}: Account is private and you don\'t follow them',
                    'is_private': True
                }), 403
            raise
        
        bio = user_details.biography or ''
        external_url = getattr(user_details, 'external_url', None) or ''
        
        # Safely convert user_details to dict and extract business info
        try:
            user_dict = user_details.dict() if hasattr(user_details, 'dict') else {}
        except:
            user_dict = {}
        
        # Also try to get business contact info directly from user_details object
        try:
            if hasattr(user_details, 'is_business') and user_details.is_business:
                if hasattr(user_details, 'business_contact_method'):
                    business_method = user_details.business_contact_method
                    if business_method:
                        if 'business_contact_method' not in user_dict:
                            user_dict['business_contact_method'] = {}
                        
                        # Check for email
                        if hasattr(business_method, 'email') and business_method.email:
                            user_dict['business_contact_method']['email'] = business_method.email
                        
                        # Check for phone number - try multiple attribute names
                        phone_number = None
                        if hasattr(business_method, 'phone_number') and business_method.phone_number:
                            phone_number = business_method.phone_number
                        elif hasattr(business_method, 'phone') and business_method.phone:
                            phone_number = business_method.phone
                        elif hasattr(business_method, 'contact_phone_number') and business_method.contact_phone_number:
                            phone_number = business_method.contact_phone_number
                        elif hasattr(business_method, 'public_phone_number') and business_method.public_phone_number:
                            phone_number = business_method.public_phone_number
                        
                        # Also check for country code separately
                        country_code = None
                        if hasattr(business_method, 'country_code') and business_method.country_code:
                            country_code = business_method.country_code
                        elif hasattr(business_method, 'phone_country_code') and business_method.phone_country_code:
                            country_code = business_method.phone_country_code
                        
                        if phone_number:
                            # Format phone number with country code
                            formatted_phone = format_phone_with_country_code(phone_number, country_code)
                            user_dict['business_contact_method']['phone_number'] = formatted_phone
                
                # Also check for phone number directly on user_details object
                if not user_dict.get('business_contact_method', {}).get('phone_number'):
                    direct_phone = None
                    direct_country_code = None
                    if hasattr(user_details, 'business_phone_number') and user_details.business_phone_number:
                        direct_phone = user_details.business_phone_number
                    elif hasattr(user_details, 'public_phone_number') and user_details.public_phone_number:
                        direct_phone = user_details.public_phone_number
                    elif hasattr(user_details, 'contact_phone_number') and user_details.contact_phone_number:
                        direct_phone = user_details.contact_phone_number
                    
                    # Check for country code on user_details
                    if hasattr(user_details, 'phone_country_code') and user_details.phone_country_code:
                        direct_country_code = user_details.phone_country_code
                    elif hasattr(user_details, 'country_code') and user_details.country_code:
                        direct_country_code = user_details.country_code
                    
                    if direct_phone:
                        if 'business_contact_method' not in user_dict:
                            user_dict['business_contact_method'] = {}
                        formatted_phone = format_phone_with_country_code(direct_phone, direct_country_code)
                        user_dict['business_contact_method']['phone_number'] = formatted_phone
        except Exception as e:
            print(f"⚠️  Could not extract business contact from object: {e}")
        
        contact_info = extract_contact_info(bio, user_dict, external_url)
        
        # Determine account type
        account_type_str = 'personal'
        is_business = False
        is_creator = False
        
        # Check for business account
        if hasattr(user_details, 'is_business') and user_details.is_business:
            is_business = True
            account_type_str = 'business'
        elif hasattr(user_details, 'is_business_account') and user_details.is_business_account:
            is_business = True
            account_type_str = 'business'
        elif user_dict.get('is_business') or user_dict.get('is_business_account'):
            is_business = True
            account_type_str = 'business'
        
        # Check for creator account
        if hasattr(user_details, 'is_creator') and user_details.is_creator:
            is_creator = True
            account_type_str = 'creator'
        elif hasattr(user_details, 'is_creator_account') and user_details.is_creator_account:
            is_creator = True
            account_type_str = 'creator'
        elif user_dict.get('is_creator') or user_dict.get('is_creator_account'):
            is_creator = True
            account_type_str = 'creator'
        
        user_data = {
            'username': user_details.username,
            'full_name': user_details.full_name,
            'bio': bio,
            'is_verified': user_details.is_verified,
            'is_private': user_details.is_private,
            'follower_count': user_details.follower_count,
            'following_count': user_details.following_count,
            'post_count': user_details.media_count,
            'external_url': user_details.external_url,
            'account_type': account_type_str,
            **contact_info
        }
        
        # Get the complete raw data from the API
        try:
            # Try to convert user_details to dict (works for Pydantic models)
            if hasattr(user_details, 'dict'):
                try:
                    raw_user_data = user_details.dict()
                except:
                    raw_user_data = {}
            else:
                raw_user_data = {}
            
            # If dict() didn't work or returned empty, extract all attributes
            if not raw_user_data:
                raw_user_data = {}
                for attr in dir(user_details):
                    if not attr.startswith('_') and not callable(getattr(user_details, attr, None)):
                        try:
                            value = getattr(user_details, attr, None)
                            # Skip methods and complex objects that can't be serialized
                            if not callable(value):
                                # Try to convert nested objects to dict if possible
                                if hasattr(value, 'dict'):
                                    try:
                                        raw_user_data[attr] = value.dict()
                                    except:
                                        raw_user_data[attr] = str(value)
                                else:
                                    raw_user_data[attr] = value
                        except Exception as attr_error:
                            # If we can't get the attribute, skip it
                            pass
            
            # Ensure we have the user_dict data merged in (includes business_contact_method)
            if user_dict:
                raw_user_data.update(user_dict)
        except Exception as e:
            logger.warning(f"Could not extract raw user data: {e}")
            # Fallback to user_dict if available
            raw_user_data = user_dict if user_dict else {}
        
        # AI Enrichment
        try:
            enrichment = enrich_profile_with_ai(raw_user_data)
            if enrichment:
                raw_user_data.update(enrichment)
        except Exception as e:
            logger.warning(f"Enrichment error: {e}")

        return jsonify({
            'status': 'success', 
            'raw_data': raw_user_data
        })
    
    except UserNotFound:
        return jsonify({'error': 'User not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/batch-process', methods=['POST'])
def batch_process():
    """Process multiple users from a list of usernames"""
    global cl
    try:
        client = get_client()
        data = request.json or {}
        
        usernames = data.get('usernames', [])
        if not usernames or not isinstance(usernames, list):
            return jsonify({'error': 'usernames array is required'}), 400
        
        results = []
        successful = 0
        failed = 0
        
        for idx, username in enumerate(usernames, 1):
            if not username or not isinstance(username, str):
                continue
            
            username = username.strip().lstrip('@')
            if not username:
                continue
            
            try:
                # Get user info
                try:
                    user_id = client.user_id_from_username(username)
                except LoginRequired:
                    cl = None
                    client = get_client(force_login=True)
                    user_id = client.user_id_from_username(username)
                except UserNotFound:
                    results.append({
                        'username': username,
                        'status': 'failed',
                        'error': 'User not found',
                        'data': None
                    })
                    failed += 1
                    continue
                
                # Get user details
                try:
                    user_details = client.user_info(user_id)
                except LoginRequired:
                    cl = None
                    client = get_client(force_login=True)
                    user_details = client.user_info(user_id)
                except Exception as e:
                    error_msg = str(e).lower()
                    if 'private' in error_msg or 'not authorized' in error_msg:
                        results.append({
                            'username': username,
                            'status': 'failed',
                            'error': 'Account is private',
                            'data': None
                        })
                    else:
                        results.append({
                            'username': username,
                            'status': 'failed',
                            'error': str(e),
                            'data': None
                        })
                    failed += 1
                    continue
                
                # Extract contact info
                bio = user_details.biography or ''
                external_url = getattr(user_details, 'external_url', None) or ''
                
                try:
                    user_dict = user_details.dict() if hasattr(user_details, 'dict') else {}
                except:
                    user_dict = {}
                
                # Extract business contact info (same logic as /user-info)
                try:
                    if hasattr(user_details, 'is_business') and user_details.is_business:
                        if hasattr(user_details, 'business_contact_method'):
                            business_method = user_details.business_contact_method
                            if business_method:
                                if 'business_contact_method' not in user_dict:
                                    user_dict['business_contact_method'] = {}
                                
                                if hasattr(business_method, 'email') and business_method.email:
                                    user_dict['business_contact_method']['email'] = business_method.email
                                
                                phone_number = None
                                if hasattr(business_method, 'phone_number') and business_method.phone_number:
                                    phone_number = business_method.phone_number
                                elif hasattr(business_method, 'phone') and business_method.phone:
                                    phone_number = business_method.phone
                                
                                country_code = None
                                if hasattr(business_method, 'country_code') and business_method.country_code:
                                    country_code = business_method.country_code
                                
                                if phone_number:
                                    formatted_phone = format_phone_with_country_code(phone_number, country_code)
                                    user_dict['business_contact_method']['phone_number'] = formatted_phone
                except:
                    pass
                
                contact_info = extract_contact_info(bio, user_dict, external_url)
                
                # Determine account type
                account_type_str = 'personal'
                if hasattr(user_details, 'is_business') and user_details.is_business:
                    account_type_str = 'business'
                elif hasattr(user_details, 'is_creator') and user_details.is_creator:
                    account_type_str = 'creator'
                
                # Get the complete raw data from the API (same as /user-info endpoint)
                try:
                    # Try to convert user_details to dict (works for Pydantic models)
                    if hasattr(user_details, 'dict'):
                        try:
                            raw_user_data = user_details.dict()
                        except:
                            raw_user_data = {}
                    else:
                        raw_user_data = {}
                    
                    # If dict() didn't work or returned empty, extract all attributes
                    if not raw_user_data:
                        raw_user_data = {}
                        for attr in dir(user_details):
                            if not attr.startswith('_') and not callable(getattr(user_details, attr, None)):
                                try:
                                    value = getattr(user_details, attr, None)
                                    # Skip methods and complex objects that can't be serialized
                                    if not callable(value):
                                        # Try to convert nested objects to dict if possible
                                        if hasattr(value, 'dict'):
                                            try:
                                                raw_user_data[attr] = value.dict()
                                            except:
                                                raw_user_data[attr] = str(value)
                                        else:
                                            raw_user_data[attr] = value
                                except Exception as attr_error:
                                    # If we can't get the attribute, skip it
                                    pass
                    
                    # Ensure we have the user_dict data merged in (includes business_contact_method)
                    if user_dict:
                        raw_user_data.update(user_dict)
                except Exception as e:
                    logger.warning(f"Could not extract raw user data: {e}")
                    # Fallback to user_dict if available
                    raw_user_data = user_dict if user_dict else {}
                
                # Merge contact_info into raw_user_data so email and other contact info is available
                if contact_info:
                    raw_user_data.update(contact_info)
                
                # AI Enrichment
                try:
                    enrichment = enrich_profile_with_ai(raw_user_data)
                    if enrichment:
                        raw_user_data.update(enrichment)
                except Exception as e:
                    logger.warning(f"Enrichment error: {e}")

                results.append({
                    'username': username,
                    'status': 'success',
                    'data': {
                        'status': 'success',
                        'raw_data': raw_user_data
                    }
                })
                successful += 1
                
            except Exception as e:
                results.append({
                    'username': username,
                    'status': 'failed',
                    'error': str(e),
                    'data': None
                })
                failed += 1
            
            # Small delay to avoid rate limiting
            if idx < len(usernames):
                time.sleep(0.5)
        
        return jsonify({
            'status': 'success',
            'total_processed': len(results),
            'successful': successful,
            'failed': failed,
            'results': results
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/csv-data', methods=['GET'])
def get_csv_data():
    """Get CSV data from the server"""
    import csv
    from pathlib import Path
    
    try:
        # Look for CSV file in docs directory
        csv_path = Path('docs/kilombo.csv')
        if not csv_path.exists():
            # Try relative to script location
            script_dir = Path(__file__).parent.parent
            csv_path = script_dir / 'docs' / 'kilombo.csv'
            if not csv_path.exists():
                return jsonify({'error': 'CSV file not found'}), 404
        
        rows = []
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(row)
        
        return jsonify({
            'status': 'success',
            'total': len(rows),
            'columns': list(rows[0].keys()) if rows else [],
            'data': rows[:1000]  # Return first 1000 rows for preview
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/csv-data/all', methods=['GET'])
def get_all_csv_data():
    """Get all CSV data from the server"""
    import csv
    from pathlib import Path
    
    try:
        # Look for CSV file in docs directory
        csv_path = Path('docs/kilombo.csv')
        if not csv_path.exists():
            # Try relative to script location
            script_dir = Path(__file__).parent.parent
            csv_path = script_dir / 'docs' / 'kilombo.csv'
            if not csv_path.exists():
                return jsonify({'error': 'CSV file not found'}), 404
        
        rows = []
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(row)
        
        return jsonify({
            'status': 'success',
            'total': len(rows),
            'columns': list(rows[0].keys()) if rows else [],
            'data': rows
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/save-users', methods=['POST'])
def save_users():
    """Save users to JSON file"""
    try:
        data = request.json or {}
        users = data.get('users', [])
        
        if not isinstance(users, list):
            return jsonify({'error': 'users must be an array'}), 400
        
        # Get the data directory path
        data_dir = Path('data')
        if not data_dir.exists():
            # Try relative to script location
            script_dir = Path(__file__).parent.parent
            data_dir = script_dir / 'data'
            data_dir.mkdir(exist_ok=True)
        
        users_file = data_dir / 'added_users.json'
        
        # Load existing users to avoid duplicates
        existing_users = []
        if users_file.exists():
            try:
                with open(users_file, 'r', encoding='utf-8') as f:
                    existing_data = json.load(f)
                    existing_users = existing_data.get('users', [])
            except Exception as e:
                logger.warning(f"Could not load existing users: {e}")
                existing_users = []
        
        # Create a set of existing usernames for quick lookup
        existing_usernames = {user.get('username') for user in existing_users if user.get('username')}
        
        # Append new users, avoiding duplicates
        new_users = []
        for user in users:
            username = user.get('username')
            if username and username not in existing_usernames:
                existing_users.append(user)
                existing_usernames.add(username)
                new_users.append(username)
        
        # Save all users
        users_data = {
            'users': existing_users,
            'last_updated': time.time()
        }
        
        with open(users_file, 'w', encoding='utf-8') as f:
            json.dump(users_data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Saved {len(new_users)} new users to {users_file}")
        
        return jsonify({
            'status': 'success',
            'total_users': len(existing_users),
            'new_users': len(new_users),
            'message': f'Saved {len(new_users)} new users'
        })
    
    except Exception as e:
        logger.error(f"Error saving users: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/load-users', methods=['GET'])
def load_users():
    """Load users from JSON file"""
    try:
        # Get the data directory path
        data_dir = Path('data')
        if not data_dir.exists():
            # Try relative to script location
            script_dir = Path(__file__).parent.parent
            data_dir = script_dir / 'data'
        
        users_file = data_dir / 'added_users.json'
        
        if not users_file.exists():
            return jsonify({
                'status': 'success',
                'users': [],
                'total': 0
            })
        
        with open(users_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            users = data.get('users', [])
        
        return jsonify({
            'status': 'success',
            'users': users,
            'total': len(users)
        })
    
    except Exception as e:
        logger.error(f"Error loading users: {e}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.getenv('FLASK_PORT', 5001))
    host = os.getenv('FLASK_HOST', '0.0.0.0')
    debug = os.getenv('FLASK_DEBUG', 'True').lower() == 'true'
    # Disable reloader by default to avoid reloading on example.py changes
    # Set FLASK_USE_RELOADER=true in .env to enable auto-reload
    use_reloader = os.getenv('FLASK_USE_RELOADER', 'False').lower() == 'true'
    
    print(f"🚀 Starting Instagram Scraper Server on http://{host}:{port}")
    print(f"📝 Debug mode: {debug}")
    print(f"🔄 Auto-reload: {use_reloader}")
    if not use_reloader:
        print("💡 Tip: Set FLASK_USE_RELOADER=true in .env to enable auto-reload")
    
    app.run(
        host=host, 
        port=port, 
        debug=debug, 
        use_reloader=use_reloader
    )

