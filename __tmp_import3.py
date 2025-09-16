try:
    import gemini_folder_once.chart_tab as c
    print('chart_tab imported ok')
except Exception as e:
    print('chart_tab import error:', type(e).__name__, e)
