try:
    import gemini_folder_once.no_trade as nt
    import inspect
    print('no_trade imported ok')
    sig = inspect.signature(nt.evaluate)
    print('evaluate sig:', sig)
except Exception as e:
    print('no_trade import error:', type(e).__name__, e)
