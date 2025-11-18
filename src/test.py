#!/usr/bin/env python3
"""
Example script to test the Instagram scraper API
"""
import requests
import json
import os

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

def get_user_info(username: str):
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
        
        # Save to JSON file
        try:
            os.makedirs('data', exist_ok=True)
            filename = f'data/user_{username}.json'
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

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("="*60)
        print("Instagram Scraper - Test Script")
        print("="*60)
        print("\nUsage:")
        print("  python test.py <username> [limit]")
        print("\nExamples:")
        print("  python test.py leomessi")
        print("  python test.py leomessi 10")
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

