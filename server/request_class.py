import datetime


class UserRequest:
    def __init__(self, iterations, body, uuid) -> None:
        self.iterations = iterations
        self.body = body
        self.uuid = uuid
        self.start_time = datetime.datetime.now()

    def to_dict(self):
        return {
            "iterations": self.iterations,
            "body": str(self.body),
            "uuid": str(self.uuid),
        }


class UserResponse:
    def __init__(self, body, uuid) -> None:
        self.body = body
        self.uuid = uuid

    def to_dict(self):
        return {
            "data": self.body,
            "uuid": self.uuid,
        }
