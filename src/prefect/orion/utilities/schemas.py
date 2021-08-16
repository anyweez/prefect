import copy
import datetime
import json
from typing import List
from uuid import UUID, uuid4

import pendulum
from pydantic import BaseModel, Field

from prefect import settings


def pydantic_subclass(
    base: BaseModel,
    name: str = None,
    include_fields: List[str] = None,
    exclude_fields: List[str] = None,
) -> BaseModel:
    """Creates a subclass of a Pydantic model that excludes certain fields.
    Pydantic models use the __fields__ attribute of their parent class to
    determine inherited fields, so to create a subclass without fields, we
    temporarily remove those fields from the parent __fields__ and use
    `create_model` to dynamically generate a new subclass.

    Args:
        base (pydantic.BaseModel): a Pydantic BaseModel
        name (str): a name for the subclass. If not provided
            it will have the same name as the base class.
        include_fields (List[str]): a set of field names to include.
            If `None`, all fields are included.
        exclude_fields (List[str]): a list of field names to exclude.
            If `None`, no fields are excluded.

    Returns:
        pydantic.BaseModel: a new model subclass that contains only the specified fields.

    Example:
        class Parent(pydantic.BaseModel):
            x: int = 1
            y: int = 2

        Child = pydantic_subclass(Parent, 'Child', exclude_fields=['y'])

        # equivalent, for extending the subclass further
        # with new fields
        class Child(pydantic_subclass(Parent, exclude_fields=['y'])):
            pass

        assert hasattr(Child(), 'x')
        assert not hasattr(Child(), 'y')
    """

    # collect field names
    field_names = set(include_fields or base.__fields__)
    excluded_fields = set(exclude_fields or [])
    if field_names.difference(base.__fields__):
        raise ValueError(
            "Included fields not found on base class: "
            f"{field_names.difference(base.__fields__)}"
        )
    elif excluded_fields.difference(base.__fields__):
        raise ValueError(
            "Excluded fields not found on base class: "
            f"{excluded_fields.difference(base.__fields__)}"
        )
    field_names.difference_update(excluded_fields)

    # create a new class that inherits from `base` but only contains the specified
    # pydantic __fields__
    new_cls = type(
        name or base.__name__,
        (base,),
        {
            "__fields__": {
                k: copy.copy(v) for k, v in base.__fields__.items() if k in field_names
            }
        },
    )

    return new_cls


class PrefectBaseModel(BaseModel):
    class Config:
        # when testing, extra attributes are prohibited to help
        # catch unintentional errors; otherwise they are ignored.
        extra = "forbid" if settings.test_mode else "ignore"

    @classmethod
    def subclass(
        cls,
        name: str = None,
        include_fields: List[str] = None,
        exclude_fields: List[str] = None,
    ) -> BaseModel:
        """Creates a subclass of this model containing only the specified fields.

        See `pydantic_subclass()`.

        Args:
            name (str, optional): a name for the subclass
            include_fields (List[str], optional): fields to include
            exclude_fields (List[str], optional): fields to exclude

        Returns:
            BaseModel: a subclass of this class
        """
        return pydantic_subclass(
            base=cls,
            name=name,
            include_fields=include_fields,
            exclude_fields=exclude_fields,
        )

    def dict(
        self, *args, shallow: bool = False, json_compatible: bool = False, **kwargs
    ) -> dict:
        """Returns a representation of the model as a Python dictionary.

        For more information on this distinction please see
        https://pydantic-docs.helpmanual.io/usage/exporting_models/#dictmodel-and-iteration


        Args:
            shallow (bool, optional): If True (default), nested Pydantic fields
                are also coerced to dicts. If false, they are left as Pydantic
                models.
            json_compatible (bool, optional): if True, objects are converted
                into json-compatible representations, similar to calling
                `json.loads(self.json())`. Not compatible with shallow=True.

        Returns:
            dict
        """

        if json_compatible and shallow:
            raise ValueError(
                "`json_compatible` can only be applied to the entire object."
            )

        # return a json-compatible representation of the object
        elif json_compatible:
            return json.loads(self.json(*args, **kwargs))

        # if shallow wasn't requested, return the standard pydantic behavior
        elif not shallow:
            return super().dict(*args, **kwargs)

        # if no options were requested, return simple dict transformation
        # to apply shallow conversion
        elif not args and not kwargs:
            return dict(self)

        # if options like include/exclude were provided, perform
        # a full dict conversion then overwrite with any shallow
        # differences
        else:
            deep_dict = super().dict(*args, **kwargs)
            shallow_dict = dict(self)
            for k, v in list(deep_dict.items()):
                if isinstance(v, dict) and isinstance(shallow_dict[k], BaseModel):
                    deep_dict[k] = shallow_dict[k]
            return deep_dict


class APIBaseModel(PrefectBaseModel):
    class Config:
        orm_mode = True

    id: UUID = Field(default_factory=uuid4)
    created: datetime.datetime = Field(None, repr=False)
    updated: datetime.datetime = Field(None, repr=False)

    def copy(self, *, update: dict = None, **kwargs):
        """
        Copying API models should return an object that could be inserted into the
        database again. The 'id', 'created', and 'updated' fields are restored to their
        default values.
        """
        update = update or dict()

        update.setdefault("id", self.__fields__["id"].get_default())
        update.setdefault("created", self.__fields__["created"].get_default())
        update.setdefault("updated", self.__fields__["updated"].get_default())

        return super().copy(update=update, **kwargs)