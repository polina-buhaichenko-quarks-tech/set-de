import pandas as pd


def _make_lookup(series: pd.Series, id_col: str, val_col: str) -> pd.DataFrame:
    #deduplication
    vals = series.dropna().unique()
    df = pd.DataFrame({val_col: sorted(vals)})
    df.index += 1
    df.index.name = id_col
    return df.reset_index()


def _parse_slot(size: str) -> tuple[int | None, int | None]:
    try:
        w, h = size.strip().split("x")
        return int(w), int(h)
    except Exception:
        return None, None


# ── main ───────────────────────────────────────────────────────────────────────

def transform(events_path: str, campaigns_path: str, users_path: str) -> dict[str, pd.DataFrame]:
   pass