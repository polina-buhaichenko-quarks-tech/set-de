import pandas as pd
from db_connector import get_connection


def _build_insert(table: str, cols: list[str]) -> str:
    placeholders = ", ".join(["%s"] * len(cols))
    col_names    = ", ".join(cols)
    return f"INSERT IGNORE INTO {table} ({col_names}) VALUES ({placeholders})"


def _to_python(val):
    if pd.isna(val):
        return None
    if hasattr(val, "item"):      # numpy scalar
        return val.item()
    if hasattr(val, "isoformat"): # date / datetime
        return val.isoformat()
    return val


def load(dataframes: dict[str, pd.DataFrame], batch_size: int = 500) -> None:
    conn   = get_connection()
    cursor = conn.cursor()

    try:
        pass
    except Exception as e:
        conn.rollback()
        print(f"  ❌  Error loading data: {e}")
        raise
    finally:
        cursor.close()
        conn.close()