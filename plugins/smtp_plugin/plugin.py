import json
import smtplib

def test_connection(request):
    data = json.loads(request.body)
    required_fields = ['smtp_server', 'smtp_port', 'username', 'password', 'encryption']
    missing_fields = [f for f in required_fields if not data.get(f)]
    if missing_fields:
        return {
            "success": False,
            "message": f"Missing fields: {', '.join(missing_fields)}"
        }

    server = data['smtp_server']
    try:
        port = int(data['smtp_port'])
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
            smtp_server = smtplib.SMTP_SSL(server, port)
        else:
            smtp_server = smtplib.SMTP(server, port)
            if encryption == "STARTTLS":
                smtp_server.starttls()

        smtp_server.login(user, password)
        smtp_server.quit()

        return {"success": True, "message": "SMTP connection successful."}

    except smtplib.SMTPException as e:
        return {"success": False, "message": f"SMTP error: {e}"}
    except Exception as e:
        return {"success": False, "message": str(e)}
