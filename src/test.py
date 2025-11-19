#!/usr/bin/env python3
"""
Example script to test the Instagram scraper API
"""
import requests
import json
import os
import csv
from pathlib import Path

BASE_URL = "http://localhost:5001"

def test_health():
    """Test health endpoint"""
    try:
        response = requests.get(f"{BASE_URL}/health", timeout=5)
        print("✅ Health check:", response.json())
        return True
    except requests.exceptions.ConnectionError:
        print(f"❌ Error: Cannot connect to server at {BASE_URL}")
        print("   Make sure the server is running: python app.py")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def get_followers(username: str, limit: int = 20):
    """Get followers of a target account"""
    try:
        response = requests.post(
            f"{BASE_URL}/followers",
            json={
                "username": username,
                "limit": limit
            },
            timeout=300  # 5 minutes for large requests
        )
    except requests.exceptions.ConnectionError:
        print(f"❌ Error: Cannot connect to server at {BASE_URL}")
        print("   Make sure the server is running: python app.py")
        return None
    except Exception as e:
        print(f"❌ Error: {e}")
        return None
    
    if response.status_code == 200:
        data = response.json()
        
        if data.get('status') != 'success':
            error_msg = data.get('error', 'Unknown error')
            print(f"❌ Error: {error_msg}")
            return None
        
        count = data.get('count', 0)
        followers = data.get('followers', [])
        
        if count == 0:
            print(f"⚠️  No followers found for @{username}")
            return data
        
        print(f"\n✅ Found {count} followers for @{username}")
        print("="*80)
        
        for i, follower in enumerate(followers, 1):
            print(f"\n{i}. @{follower.get('username', 'unknown')}")
            
            if follower.get('full_name'):
                print(f"   Name: {follower['full_name']}")
            
            bio = follower.get('bio', '')
            if bio:
                bio_display = bio[:100] + "..." if len(bio) > 100 else bio
                print(f"   Bio: {bio_display}")
            
            contact_found = False
            
            # Always show email (primary or business)
            email_to_show = follower.get('email') or follower.get('business_email')
            if email_to_show:
                print(f"   📧 Email: {email_to_show}")
                contact_found = True
                if follower.get('business_email') and follower.get('email') != follower.get('business_email'):
                    print(f"   📧 Business Email: {follower['business_email']}")
            
            # Always show phone (primary or business)
            phone_to_show = follower.get('phone') or follower.get('business_phone')
            if phone_to_show:
                print(f"   📞 Phone: {phone_to_show}")
                contact_found = True
                if follower.get('business_phone') and follower.get('phone') != follower.get('business_phone'):
                    print(f"   📞 Business Phone: {follower['business_phone']}")
            
            if follower.get('facebook_page'):
                print(f"   📘 Facebook: {follower['facebook_page']}")
                contact_found = True
            if follower.get('website'):
                print(f"   🌐 Website: {follower['website']}")
                contact_found = True
            
            if not contact_found:
                print("   ⚠️  No contact info found")
            
            follower_count = follower.get('follower_count', 0)
            post_count = follower.get('post_count', 0)
            print(f"   Followers: {follower_count:,} | Posts: {post_count:,}")
        
        # Save to JSON file
        try:
            os.makedirs('data', exist_ok=True)
            filename = f'data/followers_{username}.json'
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            print(f"\n✅ Data saved to {filename}")
        except Exception as e:
            print(f"\n⚠️  Could not save to file: {e}")
        
        return data
    else:
        try:
            error_data = response.json()
            error_msg = error_data.get('error', f'HTTP {response.status_code}')
            print(f"❌ Error ({response.status_code}): {error_msg}")
        except:
            print(f"❌ Error: HTTP {response.status_code}")
            print(f"Response: {response.text[:200]}")
        return None

def get_user_info(username: str, quiet: bool = False):
    """Get information about a specific user"""
    try:
        response = requests.post(
            f"{BASE_URL}/user-info",
            json={
                "username": username
            },
            timeout=60
        )
    except requests.exceptions.ConnectionError:
        print(f"❌ Error: Cannot connect to server at {BASE_URL}")
        print("   Make sure the server is running: python app.py")
        return None
    except Exception as e:
        print(f"❌ Error: {e}")
        return None
    
    if response.status_code == 200:
        data = response.json()
        
        if data.get('status') != 'success':
            error_msg = data.get('error', 'Unknown error')
            print(f"❌ Error: {error_msg}")
            return None
        
        user = data.get('user', {})
        
        if quiet:
            # Quiet mode: just show a summary line
            email_to_show = user.get('email') or user.get('business_email')
            phone_to_show = user.get('phone') or user.get('business_phone')
            contact_info = []
            if email_to_show:
                contact_info.append(f"📧 {email_to_show}")
            if phone_to_show:
                contact_info.append(f"📞 {phone_to_show}")
            contact_str = " | ".join(contact_info) if contact_info else "⚠️ No contact info"
            
            print(f"✅ @{user.get('username', 'unknown')} | "
                  f"Followers: {user.get('follower_count', 0):,} | "
                  f"{contact_str}")
        else:
            # Full mode: show all details
            print(f"\n✅ User Information for @{user.get('username', 'unknown')}")
            print("="*80)
            
            if user.get('full_name'):
                print(f"\n👤 Name: {user['full_name']}")
            
            print(f"🆔 User ID: {user.get('user_id', 'N/A')}")
            
            bio = user.get('bio', '')
            if bio:
                print(f"\n📝 Bio:")
                print(f"   {bio}")
            
            print(f"\n📊 Statistics:")
            print(f"   Followers: {user.get('follower_count', 0):,}")
            print(f"   Following: {user.get('following_count', 0):,}")
            print(f"   Posts: {user.get('post_count', 0):,}")
            print(f"   Verified: {'✅ Yes' if user.get('is_verified') else '❌ No'}")
            print(f"   Private: {'🔒 Yes' if user.get('is_private') else '🌐 No'}")
            
            contact_found = False
            print(f"\n📧 Contact Information:")
            
            # Always show email (primary or business)
            email_to_show = user.get('email') or user.get('business_email')
            if email_to_show:
                print(f"   📧 Email: {email_to_show}")
                contact_found = True
                if user.get('business_email') and user.get('email') != user.get('business_email'):
                    print(f"   📧 Business Email: {user['business_email']}")
            
            # Always show phone (primary or business)
            phone_to_show = user.get('phone') or user.get('business_phone')
            if phone_to_show:
                print(f"   📞 Phone: {phone_to_show}")
                contact_found = True
                if user.get('business_phone') and user.get('phone') != user.get('business_phone'):
                    print(f"   📞 Business Phone: {user['business_phone']}")
            
            if user.get('facebook_page'):
                print(f"   📘 Facebook: {user['facebook_page']}")
                contact_found = True
            if user.get('website'):
                print(f"   🌐 Website: {user['website']}")
                contact_found = True
            if user.get('external_url'):
                print(f"   🔗 External URL: {user['external_url']}")
                contact_found = True
            
            if not contact_found:
                print("   ⚠️  No contact info found")
            
            # Save to JSON file - save the raw data from the API
            try:
                os.makedirs('data', exist_ok=True)
                filename = f'data/user_{username}.json'
                # Save the raw data if available, otherwise save the full response
                raw_data = data.get('raw_data', {})
                if raw_data:
                    # Save only the raw data from Instagram API
                    save_data = {
                        'status': 'success',
                        'user': raw_data
                    }
                else:
                    # Fallback to full response if raw_data not available
                    save_data = data
                with open(filename, 'w', encoding='utf-8') as f:
                    json.dump(save_data, f, indent=2, ensure_ascii=False, default=str)
                print(f"\n✅ Data saved to {filename}")
            except Exception as e:
                print(f"\n⚠️  Could not save to file: {e}")
        
        return data
    else:
        try:
            error_data = response.json()
            error_msg = error_data.get('error', f'HTTP {response.status_code}')
            print(f"❌ Error ({response.status_code}): {error_msg}")
        except:
            print(f"❌ Error: HTTP {response.status_code}")
            print(f"Response: {response.text[:200]}")
        return None

def process_csv_batch(csv_path: str, limit: int):
    """Process users from CSV file in batch"""
    # Resolve path relative to current working directory
    csv_file = Path(csv_path)
    if not csv_file.is_absolute():
        csv_file = Path.cwd() / csv_path
    
    if not csv_file.exists():
        print(f"❌ Error: CSV file not found: {csv_path}")
        print(f"   Tried: {csv_file}")
        return False
    
    print(f"\n📄 Reading CSV file: {csv_path}")
    print(f"📊 Processing up to {limit} users...\n")
    
    users_processed = 0
    users_successful = 0
    users_failed = 0
    results = []
    
    try:
        with open(csv_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            
            for row in reader:
                if users_processed >= limit:
                    break
                
                username = row.get('Username', '').strip()
                if not username:
                    continue
                
                # Remove @ if present
                username = username.lstrip('@')
                
                users_processed += 1
                print(f"\n[{users_processed}/{limit}] Processing @{username}...")
                print("-" * 80)
                
                result = get_user_info(username, quiet=True)
                
                if result:
                    users_successful += 1
                    results.append({
                        'username': username,
                        'status': 'success',
                        'data': result
                    })
                else:
                    users_failed += 1
                    results.append({
                        'username': username,
                        'status': 'failed',
                        'data': None
                    })
                
                # Small delay to avoid rate limiting
                if users_processed < limit:
                    time.sleep(1)
        
        # Save batch results
        try:
            os.makedirs('data', exist_ok=True)
            batch_filename = f'data/batch_results_{users_processed}_users.json'
            with open(batch_filename, 'w', encoding='utf-8') as f:
                json.dump({
                    'total_processed': users_processed,
                    'successful': users_successful,
                    'failed': users_failed,
                    'results': results
                }, f, indent=2, ensure_ascii=False)
            print(f"\n✅ Batch results saved to {batch_filename}")
        except Exception as e:
            print(f"\n⚠️  Could not save batch results: {e}")
        
        print("\n" + "="*80)
        print("📊 Batch Processing Summary")
        print("="*80)
        print(f"✅ Successful: {users_successful}")
        print(f"❌ Failed: {users_failed}")
        print(f"📈 Total Processed: {users_processed}")
        print("="*80)
        
        return users_successful > 0
        
    except Exception as e:
        print(f"❌ Error reading CSV file: {e}")
        return False

if __name__ == "__main__":
    import sys
    import time
    
    # Check for CSV batch mode
    if len(sys.argv) >= 2 and sys.argv[1] == '--csv':
        # CSV batch mode: python test.py --csv [csv_file] <limit>
        if len(sys.argv) < 3:
            print("="*60)
            print("Instagram Scraper - CSV Batch Mode")
            print("="*60)
            print("\nUsage:")
            print("  python src/test.py --csv <limit>")
            print("  python src/test.py --csv <csv_file> <limit>")
            print("\nExamples:")
            print("  python src/test.py --csv 10")
            print("  python src/test.py --csv docs/kilombo.csv 50")
            print("\nNote: Make sure the server is running first:")
            print("  make dev")
            print("="*60)
            sys.exit(1)
        
        # Determine CSV file and limit
        if len(sys.argv) == 3:
            # Only limit provided, use default CSV
            csv_file = "docs/kilombo.csv"
            try:
                limit = int(sys.argv[2])
            except ValueError:
                print("❌ Error: Limit must be a number")
                sys.exit(1)
        else:
            # CSV file and limit provided
            csv_file = sys.argv[2]
            try:
                limit = int(sys.argv[3])
            except ValueError:
                print("❌ Error: Limit must be a number")
                sys.exit(1)
        
        if limit < 1:
            print("❌ Error: Limit must be greater than 0")
            sys.exit(1)
        
        if not test_health():
            print("\n💡 Tip: Start the server in another terminal with: make dev")
            sys.exit(1)
        
        success = process_csv_batch(csv_file, limit)
        sys.exit(0 if success else 1)
    
    # Single user mode (original behavior)
    if len(sys.argv) < 2:
        print("="*60)
        print("Instagram Scraper - Test Script")
        print("="*60)
        print("\nUsage:")
        print("  Single user mode:")
        print("    python src/test.py <username>")
        print("\n  CSV batch mode:")
        print("    python src/test.py --csv <limit>")
        print("    python src/test.py --csv <csv_file> <limit>")
        print("\nExamples:")
        print("  python src/test.py leomessi")
        print("  python src/test.py --csv 10")
        print("  python src/test.py --csv docs/kilombo.csv 50")
        print("\nNote: Make sure the server is running first:")
        print("  make dev")
        print("="*60)
        sys.exit(1)
    
    # Always search for user info (uses account from app login)
    username = sys.argv[1].strip().lstrip('@')  # Remove @ if present
    
    # LIMIT is kept for backward compatibility but not used for user info
    if len(sys.argv) > 2:
        try:
            limit = int(sys.argv[2])
            if limit < 1 or limit > 100:
                print("⚠️  Limit parameter ignored for user search")
        except ValueError:
            pass
    
    print(f"\n🔍 Searching for user @{username}...\n")
    
    if not test_health():
        print("\n💡 Tip: Start the server in another terminal with: make dev")
        sys.exit(1)
    
    result = get_user_info(username)
    
    if result:
        print("\n✅ Done!")
    else:
        print("\n❌ Failed to fetch user info")
        sys.exit(1)

