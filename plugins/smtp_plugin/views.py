import smtplib
from django.http import JsonResponse

def test_connection(request, data):
    required_fields = ['smtp_server', 'smtp_port', 'username', 'password', 'encryption']
    missing_fields = [f for f in required_fields if not data.get(f)]
    if missing_fields:
        return JsonResponse({
            "success": False,
            "message": f"Missing fields: {', '.join(missing_fields)}"
        })

    server = data['smtp_server']
    port = int(data['smtp_port'])
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
        return JsonResponse({"success": True, "message": "SMTP connection successful."})

    except Exception as e:
        return JsonResponse({"success": False, "message": str(e)})
