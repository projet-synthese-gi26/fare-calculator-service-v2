from django.http import JsonResponse

class ApiKeyMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # TODO: Implémenter validation clé ici (pass pour l'instant)
        pass
        response = self.get_response(request)
        return response