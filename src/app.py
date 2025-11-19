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

def login_client(client: Client, force: bool = False) -> bool:
    """Login to Instagram"""
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
                client.login(username, password)
                print("✅ Loaded existing session")
                return True
        except (LoginRequired, Exception) as e:
            print(f"⚠️  Could not load session: {e}")
            if isinstance(e, LoginRequired):
                print("🔄 Session expired, re-authenticating...")
    
    # Login (either new or re-authentication)
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
        print(f"❌ Login failed: {e}")
        raise

def get_client(force_login: bool = False) -> Client:
    """Get or create Instagram client instance"""
    global cl
    
    # Create new client if needed or if forcing re-login
    if cl is None or force_login:
        if cl is None:
            cl = Client()
        login_client(cl, force=force_login)
    
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
    }
    
    # Combine bio and external_url for searching
    search_text = bio
    if external_url:
        search_text += ' ' + external_url
    
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
        
        return jsonify({'status': 'success', 'user': user_data})
    
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
                
                results.append({
                    'username': username,
                    'status': 'success',
                    'data': {'status': 'success', 'user': user_data}
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

