from merits.tsdupd import definition
import inspect
src = inspect.getsource(definition)
idx = src.find("name=\"ALS\"")
print(src[idx:idx+800])
print("---")
# Also check Stop csv_model for location_function field
from merits.tsdupd.csv_model import Stop
print(inspect.getsource(Stop))
