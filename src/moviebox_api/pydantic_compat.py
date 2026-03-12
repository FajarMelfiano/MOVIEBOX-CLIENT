"""Pydantic replacement for restricted environments like Termux on Android"""

import typing as t

try:
    from pydantic import BaseModel, Field, HttpUrl, field_validator, ValidationError
except ImportError:
    import logging
    logging.getLogger(__name__).warning("Pydantic is not available. Using basic fallback models.")

    class ValidationError(Exception):
        pass

    class HttpUrl(str):
        pass

    def Field(*args, default_factory=None, alias=None, default=None, **kwargs):
        class _FieldParam:
            def __init__(self, factory, alias_name, fallback_default):
                self.factory = factory
                self.alias = alias_name
                self.default = fallback_default
        return _FieldParam(default_factory, alias, default)

    def field_validator(*args, **kwargs):
        def decorator(func: t.Callable) -> t.Callable:
            func.__field_validator_args__ = args
            func.__field_validator_kwargs__ = kwargs
            return func
        return decorator

    def _get_origin_type(annotation):
        origin = t.get_origin(annotation)
        if origin is not None:
            return origin
        return annotation

    def _get_args_type(annotation):
        return t.get_args(annotation)

    def _cast_value(value, annotation):
        if value is None:
            return None
        
        origin = _get_origin_type(annotation)
        
        if origin is t.Union:
            args = _get_args_type(annotation)
            if type(None) in args and value is None:
                return None
            for arg in args:
                if arg is not type(None):
                    try:
                        return _cast_value(value, arg)
                    except Exception:
                        pass
            return value

        if isinstance(origin, type) and issubclass(origin, BaseModel):
            if isinstance(value, dict):
                return origin(**value)
            return value

        if origin is list or origin is t.List:
            args = _get_args_type(annotation)
            if args and isinstance(value, list):
                item_type = args[0]
                return [_cast_value(item, item_type) for item in value]
            if isinstance(value, list):
                return value
            return value

        if origin is dict or origin is t.Dict:
            return value

        import datetime
        import uuid
        
        if annotation is datetime.date and isinstance(value, str):
            try:
                return datetime.date.fromisoformat(value[:10])
            except Exception:
                pass
                
        if annotation is datetime.datetime and isinstance(value, str):
            try:
                return datetime.datetime.fromisoformat(value.replace('Z', '+00:00'))
            except Exception:
                pass
                
        if annotation is uuid.UUID and isinstance(value, str):
            try:
                return uuid.UUID(value)
            except Exception:
                pass
                
        if annotation is float and not isinstance(value, float):
            try:
                return float(value)
            except Exception:
                pass
                
        if annotation is int and not isinstance(value, int):
            try:
                if isinstance(value, str) and '.' in value:
                    return int(float(value))
                return int(value)
            except Exception:
                pass
                
        if annotation is str and not isinstance(value, str):
            try:
                return str(value)
            except Exception:
                pass
                
        if annotation is bool and not isinstance(value, bool):
            if isinstance(value, str):
                return value.lower() in ('true', '1', 't', 'y', 'yes')
            return bool(value)
            
        return value

    class BaseModel:
        def __init__(self, **kwargs):
            cls = self.__class__
            annotations = {}
            for base in reversed(cls.__mro__):
                if hasattr(base, '__annotations__'):
                    annotations.update(base.__annotations__)
            
            mapped_kwargs = {}

            for key, val in kwargs.items():
                mapped_kwargs[key] = val

            for key, annotation in annotations.items():
                val = getattr(cls, key, None)
                if val.__class__.__name__ == "_FieldParam":
                    if val.alias and val.alias in kwargs:
                        mapped_kwargs[key] = kwargs.pop(val.alias)
                    elif key not in mapped_kwargs and val.factory:
                        mapped_kwargs[key] = val.factory()
                    elif key not in mapped_kwargs:
                        if val.default is not None:
                            mapped_kwargs[key] = val.default
                else:
                    if hasattr(cls, key) and key not in mapped_kwargs:
                        # Don't overwrite properties or methods
                        if not isinstance(getattr(cls, key), property) and not callable(getattr(cls, key)):
                            mapped_kwargs[key] = getattr(cls, key)

            for key, annotation in annotations.items():
                if key in mapped_kwargs:
                    value = mapped_kwargs[key]
                    
                    for attr_name, attr in cls.__dict__.items():
                        if hasattr(attr, "__field_validator_args__"):
                            if key in attr.__field_validator_args__:
                                try:
                                    if isinstance(attr, classmethod) or isinstance(attr, staticmethod):
                                        func = attr.__func__
                                        value = func(value)
                                    else:
                                        value = attr(value)
                                except Exception:
                                    pass
                    
                    self.__dict__[key] = _cast_value(value, annotation)

            for key, value in mapped_kwargs.items():
                if key not in self.__dict__:
                    self.__dict__[key] = value

        model_config = {}
