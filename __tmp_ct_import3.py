try:
    import gemini_folder_once.chart_tab as ct
    print('chart_tab import ok')
except Exception as e:
    print('chart_tab import error:', type(e).__name__, e)
