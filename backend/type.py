from abc import abstractmethod


class AbstractMessageSyncHandler:
    junit_version = "5"

    @abstractmethod
    def update_messages(self, messages: list[dict] | None):
        pass

    @abstractmethod
    def send_delta_message(self, message: dict[str, str]):
        pass

    @abstractmethod
    def request_client_response(
        self, prompt: str, response_type: str = "text", options: list[str] | None = None
    ) -> str | None:
        pass
