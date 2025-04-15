import json
import imaplib

def test_connection(request):
    data = json.loads(request.body)
    required_fields = ['imap_server', 'imap_port', 'username', 'password', 'encryption']
    missing_fields = [f for f in required_fields if not data.get(f)]
    if missing_fields:
        return {
            "success": False,
            "message": f"Missing fields: {', '.join(missing_fields)}"
        }

    server = data['imap_server']
    try:
        port = int(data['imap_port'])
    except ValueError:
        return {
            "success": False,
            "message": "Invalid port number."
        }

    user = data['username']
    password = data['password']
    encryption = data['encryption']

    try:
        if encryption == "SSL/TLS":
            mail = imaplib.IMAP4_SSL(server, port)
        else:
            mail = imaplib.IMAP4(server, port)
            if encryption == "STARTTLS":
                mail.starttls()

        mail.login(user, password)
        mail.logout()

        return {"success": True, "message": "IMAP Connection successful."}

    except imaplib.IMAP4.error as e:
        return {"success": False, "message": f"IMAP error: {e}"}
    except Exception as e:
        return {"success": False, "message": str(e)}
