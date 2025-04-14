from django import forms

ENCRYPTION_CHOICES = [
    ('None', 'None'),
    ('STARTTLS', 'STARTTLS'),
    ('SSL/TLS', 'SSL/TLS'),
]

class EmailPluginConfigForm(forms.Form):
    service_name = forms.CharField(
        label="Unique Service Name",
        max_length=255,
        required=True,
        help_text="A unique descriptive name for your Email service instance."
    )

    # IMAP fields
    imap_server = forms.CharField(
        label="IMAP Server URL",
        max_length=255,
        required=True,
        help_text="IMAP server address (e.g., imap.gmail.com)."
    )

    imap_port = forms.IntegerField(
        label="IMAP Server Port",
        initial=993,
        required=True,
        help_text="Port for IMAP connection (default SSL/TLS is 993)."
    )

    encryption = forms.ChoiceField(
        label="Encryption Type",
        choices=ENCRYPTION_CHOICES,
        initial='SSL/TLS',
        required=True,
        help_text="Encryption method for IMAP connections."
    )

    username = forms.CharField(
        label="Username",
        max_length=255,
        required=True,
        help_text="Email server username."
    )

    password = forms.CharField(
        label="Password",
        widget=forms.PasswordInput,
        required=True,
        help_text="Email server password."
    )

    poll_frequency = forms.IntegerField(
        label="Polling Frequency (minutes)",
        initial=5,
        required=False,
        help_text="How often RainGull checks for new emails (default: 5 minutes)."
    )

    imap_inbox = forms.CharField(
        label="IMAP Inbox Folder",
        max_length=255,
        initial='INBOX',
        required=True,
        help_text="Folder to monitor for incoming emails (usually INBOX)."
    )

    imap_processed_folder = forms.CharField(
        label="IMAP Processed Folder",
        max_length=255,
        initial='INBOX/Processed',
        required=True,
        help_text="Folder to move emails after successful processing."
    )

    imap_rejected_folder = forms.CharField(
        label="IMAP Rejected Folder",
        max_length=255,
        initial='INBOX/Rejected',
        required=True,
        help_text="Folder to move emails if processing fails or rejected."
    )

    def clean_poll_frequency(self):
        frequency = self.cleaned_data.get('poll_frequency')
        if frequency is not None and frequency <= 0:
            raise forms.ValidationError("Polling frequency must be a positive integer.")
        return frequency
