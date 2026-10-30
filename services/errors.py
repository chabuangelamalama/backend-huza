class ServiceError(Exception):
    status_code = 400

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFoundError(ServiceError):
    status_code = 404


class PermissionDeniedError(ServiceError):
    status_code = 403


class ConflictError(ServiceError):
    status_code = 409


class InvalidInputError(ServiceError):
    status_code = 422


class ServiceUnavailableError(ServiceError):
    status_code = 503
