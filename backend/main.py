from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Literal
import ee

ee.Initialize()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class Point(BaseModel):
    lat: float
    lng: float


class AnalyzeRequest(BaseModel):
    polygonCoordinates: List[Point]
    view: Literal["current", "forecast"] = "current"


# جلب NDVI الحالي
def get_current_ndvi(region):

    image = (
        ee.ImageCollection("COPERNICUS/S2_SR")
        .filterBounds(region)
        .filterDate("2024-01-01", "2024-12-31")
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 20))
        .sort("system:time_start", False)
        .first()
    )

    ndvi = image.normalizedDifference(["B8", "B4"]).rename("NDVI")

    return ndvi


# حساب NDVI المتوقع بعد شهر باستخدام trend بسيط
def get_forecast_ndvi(region):

    collection = (
        ee.ImageCollection("COPERNICUS/S2_SR")
        .filterBounds(region)
        .filterDate("2023-10-01", "2024-12-31")
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 20))
        .sort("system:time_start", False)
        .limit(2)
    )

    images = collection.toList(2)

    img_current = ee.Image(images.get(0))
    img_prev = ee.Image(images.get(1))

    ndvi_current = img_current.normalizedDifference(["B8", "B4"])
    ndvi_prev = img_prev.normalizedDifference(["B8", "B4"])

    trend = ndvi_current.subtract(ndvi_prev)

    forecast = ndvi_current.add(trend)

    return forecast.rename("NDVI")


def get_ndvi_points(polygon_coords, view):

    coords = [[p.lng, p.lat] for p in polygon_coords]
    region = ee.Geometry.Polygon([coords])

    if view == "forecast":
        ndvi = get_forecast_ndvi(region)
    else:
        ndvi = get_current_ndvi(region)

    samples = (
        ndvi.sample(
            region=region,
            scale=10,
            numPixels=450,
            geometries=True
        )
        .getInfo()
    )

    points = []

    for f in samples["features"]:

        coords = f["geometry"]["coordinates"]
        value = f["properties"]["NDVI"]

        if value > 0.55:
            status = "healthy"
        elif value > 0.35:
            status = "stressed"
        else:
            status = "critical"

        points.append({
            "lat": coords[1],
            "lng": coords[0],
            "ndvi": value,
            "status": status
        })

    return points


@app.post("/api/analyze")
def analyze(req: AnalyzeRequest):

    points = get_ndvi_points(req.polygonCoordinates, req.view)

    return {
        "view": req.view,
        "points": points
    }