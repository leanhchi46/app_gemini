try:
    import gemini_folder_once.news as n
    print('news imported; helpers present:', hasattr(n, 'next_events_for_symbol'))
except Exception as e:
    print('news import error:', type(e).__name__, e)
