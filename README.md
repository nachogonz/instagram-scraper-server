# Instagram Scraper Server

A Python Flask server that uses your Instagram account to scrape follower information and extract public contact details.

## Features

- Authenticate with your Instagram account
- Get followers of any Instagram account (by username or user ID)
- Extract public contact information (email, phone, website) from follower profiles
- RESTful API endpoints
- Session management for persistent login

## Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Create a `.env` file:
```bash
cp .env.example .env
```

3. Edit `.env` and add your Instagram credentials:
```
INSTAGRAM_USERNAME=your_username
INSTAGRAM_PASSWORD=your_password
FLASK_PORT=5001
FLASK_HOST=0.0.0.0
```

## Usage

Start the server:
```bash
python app.py
```

The server will run on `http://localhost:5001` (or the port specified in `.env`).

## API Endpoints

### Health Check
```
GET /health
```

### Login (Optional - uses .env by default)
```
POST /login
Body: {
  "username": "your_username",
  "password": "your_password"
}
```

### Get Followers
```
POST /followers
Body: {
  "username": "target_username",  // Optional if user_id provided
  "user_id": "123456789",          // Optional if username provided
  "limit": 20                      // Optional, default: 20
}
```

### Get User Info
```
POST /user-info
Body: {
  "username": "target_username",  // Optional if user_id provided
  "user_id": "123456789"          // Optional if username provided
}
```

## Example Usage

### Get 20 followers of an account:
```bash
curl -X POST http://localhost:5001/followers \
  -H "Content-Type: application/json" \
  -d '{"username": "target_account", "limit": 20}'
```

### Get followers by user ID:
```bash
curl -X POST http://localhost:5001/followers \
  -H "Content-Type: application/json" \
  -d '{"user_id": "123456789", "limit": 10}'
```

## Response Format

```json
{
  "status": "success",
  "target_user_id": "123456789",
  "target_username": "target_account",
  "count": 20,
  "followers": [
    {
      "username": "follower_username",
      "full_name": "Full Name",
      "user_id": "987654321",
      "profile_pic_url": "https://...",
      "bio": "Bio text with contact info",
      "is_verified": false,
      "is_private": false,
      "follower_count": 1000,
      "following_count": 500,
      "post_count": 150,
      "external_url": "https://...",
      "email": "email@example.com",
      "phone": "+1234567890",
      "website": "https://website.com",
      "business_email": null,
      "business_phone": null
    }
  ]
}
```

## Notes

- The server saves your Instagram session to avoid frequent logins
- Rate limiting may apply - Instagram may temporarily block requests if too many are made
- Only public information is extracted
- Make sure to comply with Instagram's Terms of Service

