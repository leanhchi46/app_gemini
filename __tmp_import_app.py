try:
    import gemini_batch_image_analyzer as app
    print('app import ok')
except Exception as e:
    print('app import error:', type(e).__name__, e)
