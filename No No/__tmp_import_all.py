try:
    import gemini_folder_once.config as c
    print('RunConfig fields ok:', 'news_cache_ttl_sec' in c.RunConfig.__annotations__)
    import gemini_folder_once.no_trade as nt
    import inspect
    print('no_trade signature:', inspect.signature(nt.evaluate))
    import gemini_folder_once.chart_tab as ct
    print('chart_tab import ok')
    import gemini_batch_image_analyzer as app
    print('app import ok')
except Exception as e:
    print('import error:', type(e).__name__, e)
