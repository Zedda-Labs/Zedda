import pytest
import pandas as pd
import zedda as zd

def test_ask_dataframe_input():
    df = pd.DataFrame({"a": [1, 2, 3]})
    # Offline mode fallback should work with dataframe
    res = zd.ask(df, "Is this a dataframe?", llm="offline")
    assert isinstance(res, str)
