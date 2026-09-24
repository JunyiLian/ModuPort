class ModuPortError(Exception): pass
class ConfigError(ModuPortError): pass
class GeometryError(ModuPortError): pass
class TopologyError(ModuPortError): pass
class AssemblyError(ModuPortError): pass
class SingularMatrixError(ModuPortError): pass
class ModalSolveError(ModuPortError): pass
class ValidationError(ModuPortError): pass
