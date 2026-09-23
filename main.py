"""MailBrief — entry point (this is what becomes MailBrief.exe).

    python main.py            settings page + icon next to the clock
    python main.py --run      weekly brief (scheduled)
    python main.py --check    hourly check: alerts, automations, forwarding (scheduled)
    python main.py --today    open "My day" (at Windows sign-in)
"""
from mailbrief.cli import main

if __name__ == '__main__':
    main()
