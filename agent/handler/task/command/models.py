from pydantic import BaseModel
from typing import Any


class Command(BaseModel):
    command: str

    @classmethod
    def from_dict(cls, data: dict) -> 'Command':
        clz = COMMAND_NAMES_TO_CLASS[data['command']]
        return clz(**data)

class StartFlowCommand(Command):
    flow: str



class SetSlotsCommand(Command):
    slots: dict[str, Any]


class CancelFlowCommand(Command):
    pass


class ResumeFlowCommand(Command):
    flow: str

COMMAND_NAMES_TO_CLASS = {
    'start_flow': StartFlowCommand,
    'cancel_flow': CancelFlowCommand,
    'resume_flow': ResumeFlowCommand,
    'set_slots': SetSlotsCommand,
}

if __name__ == '__main__':
    command = {"command": "set_slots", "slots": {"order_number": "10001"}}
    print(Command.from_dict(command))
    print(isinstance(Command.from_dict(command), SetSlotsCommand))
