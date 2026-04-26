# ==========================================
#           NATARIS BUILDINGS REFERENCE
#           All building IDs and metadata.
#           Single source of truth for all scripts.
#           Update here if game changes IDs.
# ==========================================

BUILDINGS = {
    # FIXED POSITION
    "Main Building":  {"gid_num": "15"},  # always slot 26
    "Rally Point":    {"gid_num": "16"},  # always slot 39
    "City Wall":      {"gid_num": "29"},  # always slot 40 (Roman)
    "Earth Wall":     {"gid_num": "27"},  # always slot 40 (Teuton)
    "Palisade":       {"gid_num": "28"},  # always slot 40 (Gaul)

    # USER-PLACED - slot defined in template JSONs
    "Warehouse":      {"gid_num": "10"},
    "Granary":        {"gid_num": "11"},
    "Marketplace":    {"gid_num": "17"},
    "Embassy":        {"gid_num": "18"},
    "Hero's Mansion": {"gid_num": "37"},
    "Residence":      {"gid_num": "25"},
    "Palace":         {"gid_num": "14"},
    "Trade Office":   {"gid_num": "26"},
    "Cranny":         {"gid_num": "23"},
    "Barracks":       {"gid_num": "19"},
    "Stable":         {"gid_num": "20"},
    "Blacksmith":     {"gid_num": "12"},
    "Academy":        {"gid_num": "22"},
    "Workshop":       {"gid_num": "21"},
    "Town Hall":      {"gid_num": "24"},

    # TRIBE-SPECIFIC
    "Brewery":        {"gid_num": "35"},  # Teuton only
    "Trapper":        {"gid_num": "36"},  # Gaul only

    # RESOURCE BONUS
    "Grain Mill":     {"gid_num": "8"},
    "Bakery":         {"gid_num": "9"},
    "Sawmill":        {"gid_num": "5"},
    "Brickyard":      {"gid_num": "6"},
    "Iron Foundry":   {"gid_num": "7"},
}
