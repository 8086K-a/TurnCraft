from pathlib import Path

from .manager import FlowManager
from .models import FlowsList


class FlowLoader:
    def load(self, path: Path) -> FlowsList:
        return self.load_many([path])

    def load_many(self, paths: list[Path]) -> FlowsList:
        manager = FlowManager()
        manager.load_many(paths)
        return FlowsList(manager)

if __name__ == '__main__':
    root = Path(__file__).parents[3]
    system_flows_path = root / 'flow_config' / 'system_flows.yml'
    user_flows_path = root / 'flow_config' / 'user_flows.yml'

    loader = FlowLoader()
    data1 = loader.load_many([system_flows_path, user_flows_path])
    print(data1)
