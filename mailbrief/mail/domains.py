"""Known mail providers and free-mail domains."""


KNOWN_HOSTS = {
    'gmail.com': 'imap.gmail.com', 'googlemail.com': 'imap.gmail.com',
    'yahoo.com': 'imap.mail.yahoo.com', 'ymail.com': 'imap.mail.yahoo.com',
    'icloud.com': 'imap.mail.me.com', 'me.com': 'imap.mail.me.com', 'mac.com': 'imap.mail.me.com',
    'outlook.com': 'outlook.office365.com', 'hotmail.com': 'outlook.office365.com',
    'live.com': 'outlook.office365.com', 'msn.com': 'outlook.office365.com',
    'aol.com': 'imap.aol.com', 'gmx.com': 'imap.gmx.com', 'zoho.com': 'imap.zoho.com',
}


MICROSOFT = {'outlook.com', 'hotmail.com', 'live.com', 'msn.com'}


def guess_host(address: str) -> str:
    domain = address.rsplit('@', 1)[-1].lower().strip()
    return KNOWN_HOSTS.get(domain, f'imap.{domain}')


FREE_MAIL = {'gmail.com', 'googlemail.com', 'yahoo.com', 'hotmail.com', 'outlook.com', 'live.com', 'icloud.com',
             'walla.co.il', 'walla.com', 'bezeqint.net', 'netvision.net.il', 'zahav.net.il', 'aol.com', 'gmx.com'}
