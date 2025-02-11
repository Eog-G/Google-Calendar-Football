import requests
from datetime import datetime, timedelta
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
import os.path
import pickle
import json
from email.mime.text import MIMEText
import base64
import zoneinfo  # Add this to imports at top of file

# API configuration
def get_api_credentials():
    try:
        with open('credentials.json', 'r') as f:
            credentials = json.loads(f.read())
            return credentials.get('football_data_api_key')
    except Exception as e:
        print(f"Error reading API key from credentials.json: {e}")
        return None

API_KEY = get_api_credentials()
if not API_KEY:
    raise ValueError("Failed to load API key from credentials.json")

TEAM_ID = 64

# Set up the API request headers
headers = {'X-Auth-Token': API_KEY}

def get_google_calendar_service():
    SCOPES = [
        'https://www.googleapis.com/auth/calendar.events',
        'https://www.googleapis.com/auth/gmail.send',
        'https://www.googleapis.com/auth/gmail.readonly'
    ]
    creds = None
    
    # Load existing credentials if available
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)
    
    # Refresh credentials if expired
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        
        # Save credentials for future use
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)
    
    calendar_service = build('calendar', 'v3', credentials=creds)
    gmail_service = build('gmail', 'v1', credentials=creds)
    return calendar_service, gmail_service

def event_exists(service, match):
    match_date = datetime.strptime(match['utcDate'], '%Y-%m-%dT%H:%M:%SZ')
    is_tbc = match_date.hour == 0 and match_date.minute == 0
    
    # Search for events on the same day
    start_of_day = match_date.replace(hour=0, minute=0, second=0).isoformat() + 'Z'
    end_of_day = match_date.replace(hour=23, minute=59, second=59).isoformat() + 'Z'
    
    # Create the event summary we're looking for
    base_summary = f"{match['homeTeam']['name']} vs {match['awayTeam']['name']}"
    tbc_summary = base_summary + " ⚠️ Time TBC"
    
    try:
        events_result = service.events().list(
            calendarId='primary',
            timeMin=start_of_day,
            timeMax=end_of_day,
            singleEvents=True
        ).execute()
        
        events = events_result.get('items', [])
        
        # Check for both regular and TBC versions of the event
        for event in events:
            event_summary = event.get('summary', '')
            if event_summary in [base_summary, tbc_summary]:
                return True
                
        return False
    except Exception as e:
        print(f"Error checking for existing event: {e}")
        return False

def add_fixture_to_calendar(service, match, summary):
    try:
        match_date = datetime.strptime(match['utcDate'], '%Y-%m-%dT%H:%M:%SZ')
        is_tbc = match_date.hour == 0 and match_date.minute == 0
        
        try:
            uk_zone = zoneinfo.ZoneInfo('Europe/London')
            match_date = match_date.replace(tzinfo=zoneinfo.ZoneInfo('UTC')).astimezone(uk_zone)
        except zoneinfo.ZoneInfoNotFoundError:
            print("Error: Timezone data not found. Please install tzdata package using:")
            print("pip install tzdata")
            raise
        
        if is_tbc:
            # For TBC times, create an all-day event
            event = {
                'summary': summary,
                'description': f"Competition: {match['competition']['name']}\nTeam ID: {TEAM_ID}",
                'start': {
                    'date': match_date.date().isoformat(),
                },
                'end': {
                    'date': match_date.date().isoformat(),
                },
                'reminders': {
                    'useDefault': True
                },
                'colorId': '11'
            }
        else:
            # For events with known times
            end_time = match_date.replace(hour=match_date.hour + 2)
            event = {
                'summary': summary,
                'description': f"Competition: {match['competition']['name']}\nTeam ID: {TEAM_ID}",
                'start': {
                    'dateTime': match_date.isoformat(),
                    'timeZone': 'Europe/London',
                },
                'end': {
                    'dateTime': end_time.isoformat(),
                    'timeZone': 'Europe/London',
                },
                'reminders': {
                    'useDefault': True
                },
                'colorId': '11'
            }

        try:
            event = service.events().insert(calendarId='primary', body=event).execute()
            print(f"Added to calendar: {event.get('htmlLink')}")
        except Exception as e:
            print(f"Error adding event to calendar: {e}")
    except Exception as e:
        print(f"Error adding fixture to calendar: {e}")

def get_liverpool_fixtures(existing_events=None):
    if existing_events is None:
        existing_events = {}
    
    # API endpoint for team matches
    url = f'http://api.football-data.org/v4/teams/{TEAM_ID}/matches?status=SCHEDULED'
    
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        
        matches = response.json()['matches']
        calendar_service, gmail_service = get_google_calendar_service()
        
        print("Adding Liverpool Fixtures to Calendar:")
        print("-" * 50)
        
        # Initialize counters
        stats = {
            'added_confirmed': 0,    # Events added with confirmed times
            'added_tbc': 0,          # Events added as all-day TBC
            'total': len(matches)    # Total events processed
        }
        
        for match in matches:
            match_date = datetime.strptime(match['utcDate'], '%Y-%m-%dT%H:%M:%SZ')
            is_tbc = match_date.hour == 0 and match_date.minute == 0
            
            base_summary = f"{match['homeTeam']['name']} vs {match['awayTeam']['name']}"
            tbc_summary = base_summary + " ⚠️ Time TBC"
            summary = tbc_summary if is_tbc else base_summary
            
            formatted_date = match_date.strftime('%d %B %Y')
            if is_tbc:
                formatted_date += " ⚠️ Time TBC"
            else:
                formatted_date += f", {match_date.strftime('%H:%M')}"
            
            print(f"{formatted_date}")
            print(f"{match['homeTeam']['name']} vs {match['awayTeam']['name']}")
            print(f"Competition: {match['competition']['name']}")
            
            # Add to Google Calendar
            add_fixture_to_calendar(calendar_service, match, summary)
            if is_tbc:
                stats['added_tbc'] += 1
            else:
                stats['added_confirmed'] += 1
            
            print("-" * 50)

        # Create detailed summary for email
        summary = (
            f"Script Run Summary:\n\n"
            f"🔄 Calendar refreshed - removed and re-added all fixtures\n\n"
            f"Total fixtures processed: {stats['total']}\n"
            f"✅ Added with confirmed times: {stats['added_confirmed']}\n"
            f"⚠️ Added as TBC all-day events: {stats['added_tbc']}\n\n"
        )
        
        # Send email notification with detailed stats
        send_email_notification(gmail_service, "Fixture Update Complete", summary)

    except requests.exceptions.RequestException as e:
        error_message = f"Error fetching fixtures from football-data.org API: {str(e)}"
        print(error_message)
        try:
            _, gmail_service = get_google_calendar_service()
            send_email_notification(gmail_service, f"ERROR: {error_message}")
        except Exception as email_error:
            print(f"Failed to send error notification email: {email_error}")

def send_email_notification(service, action, details=''):
    try:
        # Get user's email address
        profile = service.users().getProfile(userId='me').execute()
        sender = profile['emailAddress']
        
        # Create message
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        subject = f"⚽ Liverpool FC Fixtures Update - {action} ({timestamp})"
        
        body = f"The Liverpool fixtures script was run at {timestamp}\n\n"
        if details:
            body += f"{details}\n"
        
        message = MIMEText(body)
        message['to'] = sender
        message['from'] = sender
        message['subject'] = subject
        # Add importance headers
        message['X-Priority'] = '1'
        message['X-MSMail-Priority'] = 'High'
        message['Importance'] = 'High'
        
        # Encode the message
        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
        
        # Send the email
        service.users().messages().send(
            userId='me',
            body={'raw': raw_message}
        ).execute()
        
        print(f"High importance notification email sent to {sender}")
    except Exception as e:
        print(f"Error sending email notification: {e}")

def delete_events(service, team_id):
    """Delete recent past and all future events for a specific team ID from the calendar and return their details"""
    try:
        week_ago = (datetime.utcnow() - timedelta(days=7)).isoformat() + 'Z'
        events_result = service.events().list(
            calendarId='primary',
            timeMin=week_ago,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        
        events = events_result.get('items', [])
        existing_events = {}  # Store details of deleted events
        
        if not events:
            print("No upcoming events found")
            return 0, existing_events
            
        deleted_count = 0
        for event in events:
            description = event.get('description', '')
            if f"Team ID: {team_id}" in description:
                print(f"Deleting: {event['summary']}")
                # Store event details before deletion
                is_all_day = 'date' in event.get('start', {})
                start_time = event.get('start', {}).get('dateTime' if not is_all_day else 'date')
                existing_events[event['summary']] = {
                    'start_time': start_time,
                    'is_all_day': is_all_day
                }
                
                service.events().delete(
                    calendarId='primary',
                    eventId=event['id']
                ).execute()
                deleted_count += 1
                
        if deleted_count > 0:
            print(f"Successfully deleted {deleted_count} events for team ID: {team_id}")
        else:
            print(f"No events found for team ID: {team_id}")
            
        return deleted_count, existing_events
    
    except Exception as e:
        print(f"An error occurred: {e}")
        return 0, {}

def main():
    calendar_service, gmail_service = get_google_calendar_service()
    
    # Delete existing fixtures first and get their details
    print("Removing existing fixtures...")
    deleted_count, existing_events = delete_events(calendar_service, TEAM_ID)
    
    # Add new fixtures
    print("\nAdding new fixtures...")
    get_liverpool_fixtures(existing_events)

if __name__ == '__main__':
    main()
