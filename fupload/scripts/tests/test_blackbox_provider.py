import unittest
from fupload_cli.blackbox import Blackbox

class BlackboxProviderTests(unittest.TestCase):
    def test_read_and_mutations_use_workshop_routes(self):
        state = {"module": {"id": 7, "name": "taptool"}, "versions": []}
        def transport(method, path, body, query):
            if path.endswith("module/list/"): return {"status":"ok","result":{"moduleList":[state["module"]]}}
            if path.endswith("module/detail/"): return {"status":"ok","result":{"module":state["module"]}}
            if path.endswith("module/update/"): state["module"].update(body); return {"status":"ok","result":{}}
            if path.endswith("module_version/list/"): return {"status":"ok","result":{"versionList":state["versions"]}}
            if path.endswith("module_version/upsert/"):
                row={**body,"id":body.get("versionId",9),"gameVersions":body["gameVersions"].split(","),"fileUrlHeybox":body["fileUrl"]}; state["versions"]=[row]; return {"status":"ok","result":{}}
            if path.endswith("module_version/delete/"): state["versions"]=[]; return {"status":"ok","result":{}}
            raise AssertionError(path)
        provider = Blackbox({"verify_attempts": 1}, transport)
        self.assertEqual(provider.plugin_list()["total_count"], 1)
        self.assertTrue(provider.execute_write("plugin", "edit", {"id":7,"name":"changed"})["verified"])
        self.assertTrue(provider.execute_write("version", "create", {"module_id":7,"name":"v","type":3,"game_versions":["1.0"],"file_url":"https://x"})["verified"])
        self.assertTrue(provider.execute_write("version", "delete", {"module_id":7,"version_id":9})["verified"])

if __name__ == "__main__": unittest.main()
