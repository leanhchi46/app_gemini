try:
    import gemini_batch_image_analyzer as app
    print('import ok')
except Exception as e:
    print('import error:', type(e).__name__, e)
