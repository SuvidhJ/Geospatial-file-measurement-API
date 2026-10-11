from uuid import UUID

from pydantic import BaseModel, Field

from app.services.volumes import BaseMethod, DemInfo, FeatureVolume


class DemRead(BaseModel):
    crs: str
    cell_size_m: tuple[float, float] = Field(description="Cell width and height in metres.")
    width: int
    height: int


class FeatureVolumeRead(BaseModel):
    index: int = Field(description="Index of the polygon feature in the file.")
    measured: bool
    reason: str | None = Field(description="Why the feature was not measured, if it wasn't.")
    base_elevation_m: float | None = Field(description="Elevation of the base plane.")
    cut_volume_m3: float | None = Field(description="Material above the base plane.")
    fill_volume_m3: float | None = Field(description="Void below the base plane.")
    net_volume_m3: float | None = Field(description="cut - fill")
    surface_area_m2: float | None = Field(description="3D area of the DEM surface.")
    planimetric_area_m2: float | None = Field(description="2D area of the DEM cells used.")
    dem_coverage_pct: float | None = Field(description="Share of the polygon with DEM data.")
    warnings: list[str]


class VolumeTotals(BaseModel):
    cut_volume_m3: float
    fill_volume_m3: float
    net_volume_m3: float


class VolumeReport(BaseModel):
    file_id: UUID
    base_method: BaseMethod
    dem: DemRead
    totals: VolumeTotals
    items: list[FeatureVolumeRead]


def volume_report(
    file_id: UUID, base_method: BaseMethod, dem: DemInfo, volumes: list[FeatureVolume]
) -> VolumeReport:
    measured = [v for v in volumes if v.measured]
    return VolumeReport(
        file_id=file_id,
        base_method=base_method,
        dem=DemRead(crs=dem.crs, cell_size_m=dem.cell_size_m, width=dem.width, height=dem.height),
        totals=VolumeTotals(
            cut_volume_m3=round(sum(v.cut_volume_m3 or 0 for v in measured), 2),
            fill_volume_m3=round(sum(v.fill_volume_m3 or 0 for v in measured), 2),
            net_volume_m3=round(sum(v.net_volume_m3 or 0 for v in measured), 2),
        ),
        items=[
            FeatureVolumeRead(
                index=v.index,
                measured=v.measured,
                reason=v.reason,
                base_elevation_m=_round(v.base_elevation_m, 3),
                cut_volume_m3=_round(v.cut_volume_m3, 2),
                fill_volume_m3=_round(v.fill_volume_m3, 2),
                net_volume_m3=_round(v.net_volume_m3, 2),
                surface_area_m2=_round(v.surface_area_m2, 2),
                planimetric_area_m2=_round(v.planimetric_area_m2, 2),
                dem_coverage_pct=_round(v.dem_coverage_pct, 2),
                warnings=v.warnings,
            )
            for v in volumes
        ],
    )


def _round(value: float | None, digits: int) -> float | None:
    return None if value is None else round(value, digits)
