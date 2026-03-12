import sys
from pathlib import Path
sys.path.insert(0, str(Path(r"c:\Users\setya\Documents\MOVIEBOX-CLIENT\src").resolve()))

from datetime import date
from moviebox_api.pydantic_compat import BaseModel

class MyModel(BaseModel):
    releaseDate: date

m = MyModel(releaseDate="2013-10-10")
print(type(m.releaseDate), repr(m.releaseDate))
if hasattr(m.releaseDate, "year"):
    print("Year:", m.releaseDate.year)
else:
    print("No year attribute!")
