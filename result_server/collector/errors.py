"""Value-free errors for local delivery and transport boundaries."""


class DeliveryError(RuntimeError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code
