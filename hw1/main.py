import argparse
from transform_utils import transform
from load_utils import load


def parse_args():
    p = argparse.ArgumentParser(description="ETL: CSV → normalised MySQL")
    p.add_argument("--events",    required=True, help="Path to ad_events.csv")
    p.add_argument("--campaigns", required=True, help="Path to campaigns.csv")
    p.add_argument("--users",     required=True, help="Path to users.csv")
    return p.parse_args()


def main():
    args = parse_args()

    print("▶  Transforming CSVs...")
    dataframes = transform(args.events, args.campaigns, args.users)
    print(f"   Tables ready: {list(dataframes.keys())}\n")

    print("▶  Loading into MySQL...")
    load(dataframes)

    print("\n✅  ETL complete.")


if __name__ == "__main__":
    main()