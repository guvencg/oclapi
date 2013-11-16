from rest_framework import mixins, status
from rest_framework.generics import RetrieveAPIView, ListAPIView
from rest_framework.response import Response
from concepts.models import Concept, ConceptVersion
from concepts.serializers import ConceptCreateSerializer, ConceptListSerializer, ConceptDetailSerializer, ConceptVersionListSerializer
from oclapi.permissions import HasAccessToVersionedObject
from oclapi.views import SubResourceMixin, VersionedResourceChildMixin


class ConceptBaseView(SubResourceMixin):
    lookup_field = 'concept'
    pk_field = 'mnemonic'
    model = Concept
    queryset = Concept.objects.filter(is_active=True)
    permission_classes = (HasAccessToVersionedObject,)


class ConceptRetrieveUpdateDestroyView(ConceptBaseView, RetrieveAPIView):
    serializer_class = ConceptDetailSerializer


class ConceptListView(ListAPIView):
    model = Concept
    queryset = Concept.objects.filter(is_active=True)
    serializer_class = ConceptListSerializer


class ConceptCreateView(ConceptBaseView,
                        mixins.CreateModelMixin):

    def dispatch(self, request, *args, **kwargs):
        if request.method != 'POST':
            delegate_view = ConceptVersionListView.as_view()
            return delegate_view(request, *args, **kwargs)
        return super(ConceptCreateView, self).dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        self.serializer_class = ConceptCreateSerializer
        return self.create(request, *args, **kwargs)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.DATA, files=request.FILES)
        if serializer.is_valid():
            self.pre_save(serializer.object)
            self.object = serializer.save(force_insert=True, owner=request.user, parent_resource=self.parent_resource)
            if serializer.is_valid():
                self.post_save(self.object, created=True)
                headers = self.get_success_headers(serializer.data)
                return Response(serializer.data, status=status.HTTP_201_CREATED,
                                headers=headers)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ConceptVersionBaseView(VersionedResourceChildMixin):
    lookup_field = 'version'
    pk_field = 'mnemonic'
    model = ConceptVersion
    queryset = ConceptVersion.objects.filter(is_active=True)
    permission_classes = (HasAccessToVersionedObject,)
    child_list_attribute = 'concepts'


class ConceptVersionListView(ConceptVersionBaseView, ListAPIView):
    serializer_class = ConceptVersionListSerializer
