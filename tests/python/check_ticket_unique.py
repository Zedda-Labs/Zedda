import pandas as pd

df = pd.read_csv("tests/data/titanic.csv")
tickets = df["Ticket"].dropna()
print(f"Total Ticket rows: {len(tickets)}")
print(f"Unique Ticket values: {tickets.nunique()}")
