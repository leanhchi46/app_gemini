try:
    import gemini_batch_image_analyzer as app
    print('app import ok')
    a = app.GeminiFolderOnceApp
    print('has _log_no_trade:', hasattr(a, '_log_no_trade'))
    import gemini_folder_once.auto_trade as at
    print('auto_trade import ok')
except Exception as e:
    print('import error:', type(e).__name__, e)
