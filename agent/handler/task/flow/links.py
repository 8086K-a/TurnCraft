from pydantic import BaseModel


class FlowStepLink(BaseModel):
    target: str


class StaticLink(FlowStepLink):
    pass


class ConditionalLink(FlowStepLink):
    condition: str


class FallbackLink(FlowStepLink):
    pass
