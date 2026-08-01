import re
from database import DatabaseManager
from scraper import DeepCrawler
import os
import sqlite3

def test_email_filtering():
    print("Testing email filtering & email-validator integration...")
    crawler = DeepCrawler(None)
    
    junk_emails = [
        "605a7baede844d278b89dc95ae0a9123@sentry-next.wixpress.com",
        "388fe63e6063cc241ca2a1b0f52622a3@o61919.ingest.us.sentry.io",
        "demo@example.com",
        "example@mysite.com",
        "user@yourdomain.com",
        "test@domain.com",
        "invalid-email-address-without-at-sign.com",
        "services-settlement@2x-447x245.webp",
        "noreply@company.com",
        "test@test.com"
    ]
    
    good_emails = [
        "john.doe@company.com",
        "info@business.com.au",
        "contact@startup.io",
        "support@fixare.studio"
    ]
    
    for email in junk_emails:
        assert not crawler._is_valid_email(email), f"Failed: Junk email {email} was accepted"
        print(f"  [PASS] Correctly rejected: {email}")

    for email in good_emails:
        assert crawler._is_valid_email(email), f"Failed: Good email {email} was rejected"
        print(f"  [PASS] Correctly accepted: {email}")

def test_multi_person_extraction():
    from bs4 import BeautifulSoup
    print("\nTesting multi-person extraction logic...")
    
    html = """
    <div class="team-member">
        <h3 class="name">John Smith</h3>
        <p class="role">CEO & Founder</p>
        <a href="https://linkedin.com/in/jsmith">LinkedIn</a>
        <p>Email: john@business.com</p>
    </div>
    <div class="person">
        <span class="member-name">Jane Doe</span>
        <div class="position">Lead Developer</div>
        <p>Contact: +44 123 456 789</p>
    </div>
    """
    soup = BeautifulSoup(html, 'html.parser')
    crawler = DeepCrawler(None)
    members = crawler._extract_team_members(soup, "https://test.com")
    
    assert len(members) == 2, f"Expected 2 members, found {len(members)}"
    assert members[0]["name"] == "John Smith", f"Expected John Smith, found {members[0]['name']}"
    assert "CEO" in members[0]["role"], "Role missing for John Smith"
    assert members[0]["linkedin"] == "https://linkedin.com/in/jsmith", "LinkedIn missing"
    assert members[1]["name"] == "Jane Doe", f"Expected Jane Doe, found {members[1]['name']}"
    print("  [PASS] Multi-person extraction logic working")

def test_database():
    print("\nTesting database integration...")
    db = DatabaseManager("test_leads.db")
    
    test_lead = {
        "place_id": "test_id_123",
        "name": "Test Business",
        "query": "test query",
        "email": "contact@testbusiness.com",
        "owner_name": "Jane Smith",
        "website": "https://testbusiness.com"
    }
    
    # Test insertion
    success = db.insert_lead(test_lead)
    assert success, "Failed to insert lead"
    print("  [PASS] Lead inserted successfully")
    
    # Test contact insertion
    contact = {
        "lead_place_id": "test_id_123",
        "name": "Employee One",
        "role": "Manager",
        "email": "mngr@test.com",
        "phone": "00000000",
        "linkedin": "N/A"
    }
    success = db.insert_contact(contact)
    assert success, "Failed to insert contact"
    print("  [PASS] Contact inserted successfully")
    
    # Test Smart Merge
    test_lead_incomplete = {
        "place_id": "test_id_123",
        "name": "Test Business UPDATED",
        "email": "N/A", # Should not overwrite contact@testbusiness.com
        "owner_name": "N/A", # Should not overwrite Jane Smith
        "website": "https://new-website.com" # Should overwrite
    }
    db.insert_lead(test_lead_incomplete)
    
    # Verify merge
    with sqlite3.connect(db.db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT email, owner_name, website FROM leads WHERE place_id = ?", ("test_id_123",))
        row = cursor.fetchone()
        assert row[0] == "contact@testbusiness.com", f"Merge failed: email overwritten with {row[0]}"
        assert row[1] == "Jane Smith", f"Merge failed: owner_name overwritten with {row[1]}"
        assert row[2] == "https://new-website.com", f"Merge failed: website not updated to {row[2]}"
    print("  [PASS] Smart Merge logic working")

    # Cleanup
    if os.path.exists("test_leads.db"):
        os.remove("test_leads.db")
    print("  [PASS] Database cleanup done")

if __name__ == "__main__":
    try:
        test_email_filtering()
        test_multi_person_extraction()
        test_database()
        print("\nAll tests passed successfully!")
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"\nTests failed: {e}")
        exit(1)
