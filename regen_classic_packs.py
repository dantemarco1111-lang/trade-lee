"""
Regenerates only the 8 classic breakout/fakeout pack files (stocks/futures/
forex/crypto x 5m/15m) after adding consolidation_minutes/prior_period_high/
prior_period_low to the record schema. Deliberately does NOT call
generate_market_packs() (which rmtree's the whole drills/ dir) so the LSW
and strategy-pack JSON files already on disk are left untouched.

Run: python regen_classic_packs.py
"""
from generate_drills import MARKET_PACKS, TIMEFRAMES, build_pack

for pack_key, pack_cfg in MARKET_PACKS.items():
    for timeframe, tf_cfg in TIMEFRAMES.items():
        base_name, ext = pack_cfg["output_file"].rsplit(".", 1)
        output_file = f"{base_name}{tf_cfg['filename_suffix']}.{ext}"
        build_pack(pack_key, pack_cfg, timeframe, tf_cfg["interval"], output_file)
