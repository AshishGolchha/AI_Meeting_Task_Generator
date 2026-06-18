def detect_meeting_source(link: str):

    link = link.lower()

    if "meet.google.com" in link:
        return "google_meet"

    elif "zoom.us" in link:
        return "zoom"

    else:
        return "other"