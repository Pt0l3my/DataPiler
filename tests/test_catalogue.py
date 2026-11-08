"""The catalogue (build plan §4.7, §8.3): every server row's ops pass jobs.check(builtin=True); the bundles as design
§6; no built-in write_share table carries a fetched column."""

import _repo  # noqa: F401

import json
import re
import unittest

from datapiler import catalogue, fields, jobs


def builtin(row_id: str) -> jobs.Job:
    doc = {"format": jobs.FORMAT, "id": catalogue.job_id(row_id), "title": catalogue.row(row_id).name,
           "ops": catalogue.ops_for(row_id)}
    return jobs.check(json.dumps(doc).encode(), known_ids=(), share_names={}, builtin=True)


SERVER = [r.id for r in catalogue.ROWS if "server" in r.sources]
GUIDED = [r.id for r in catalogue.ROWS if "guided" in r.sources]


class CatalogueTest(unittest.TestCase):
    def test_the_rows(self):
        self.assertEqual([r.id for r in catalogue.ROWS], ["character_rows", "character_names", "dialogue_links",
                                                          "map_placements", "places", "place_names"])
        self.assertEqual(SERVER, ["character_rows", "dialogue_links", "map_placements", "places"])
        self.assertEqual(GUIDED, ["character_names", "place_names"])
        for r in catalogue.ROWS:
            # DP8: Extract writes the workspace, and at most a counts-only summary share file
            self.assertEqual(r.goes_to, "workspace+counts" if "server" in r.sources else "workspace")
            self.assertEqual(len(r.sources), 1)
            self.assertEqual(bool(r.steps), "guided" in r.sources)
        self.assertEqual(catalogue.row("character_names").containers, ("item", "item_dlc01", "item_dlc02"))
        # P3's lead: the place names come in the same exports
        self.assertEqual(catalogue.row("place_names").containers, ("item", "item_dlc01", "item_dlc02"))
        self.assertTrue(catalogue.row("map_placements").needs_maps)

    def test_every_server_rows_ops_pass_the_check(self):
        for rid in SERVER:
            with self.subTest(rid):
                job = builtin(rid)
                self.assertTrue(job.uses_link)
                self.assertEqual(job.share_name, "extract-" + rid)
                local = [o for o in job.ops if o["op"] == "write_local"]
                self.assertEqual([o["name"] for o in local], [rid])

    def test_a_guided_row_has_no_ops(self):
        for rid in GUIDED:
            with self.assertRaises(KeyError):
                catalogue.ops_for(rid)

    def test_the_bundles_as_design_6(self):
        self.assertEqual(catalogue.BUNDLES, {
            "roster": ("character_rows", "character_names", "dialogue_links"),
            "placements": ("map_placements",),
            "places": ("places", "place_names"),
            "everything": ("character_rows", "character_names", "dialogue_links", "map_placements", "places",
                           "place_names"),
        })

    def test_no_built_in_share_table_carries_a_fetched_column(self):
        for rid in SERVER:
            job = builtin(rid)
            fetched = set(c for p in fields.PARAMS.values() for c in p) | {c for c, _ in jobs.PLACEMENT_COLUMNS}
            made_by = {o["as"]: o for o in job.ops if "as" in o}
            for o in job.ops:
                if o["op"] != "write_share":
                    continue
                for table, cols in o["columns"].items():
                    with self.subTest(rid=rid, table=table):
                        self.assertEqual(cols, ["count"])
                        self.assertFalse(set(cols) & fetched)
                        self.assertEqual(made_by[table]["op"], "count")
                        self.assertFalse(made_by[table].get("by"))     # a total, never per value of a column

    def test_the_ops_are_copies(self):
        a = catalogue.ops_for("character_rows")
        a[0]["fields"].append("teamName")
        self.assertNotIn("teamName", catalogue.ops_for("character_rows")[0]["fields"])

    def test_share_names(self):
        self.assertEqual(catalogue.share_names(), {"extract-" + r: "extract-" + r for r in SERVER})

    def test_public(self):
        pub = catalogue.public()
        self.assertEqual(set(pub), {"rows", "bundles"})
        self.assertEqual(pub["bundles"]["roster"], ["character_rows", "character_names", "dialogue_links"])
        for r in pub["rows"]:
            self.assertEqual(set(r), {"id", "name", "help", "sources", "gives", "goes_to", "steps"})
        steps = next(r["steps"] for r in pub["rows"] if r["id"] == "character_names")
        self.assertTrue(any("<WORKSPACE>\\inbox" in s for s in steps))
        self.assertTrue(any("`item`" in s for s in steps))
        text = json.dumps(pub)
        self.assertFalse(re.search(r"[A-Za-z]:\\\\|/home/|/Users/", text))


if __name__ == "__main__":
    unittest.main()
