idf_component_register(
    SRCS "main.c"
    INCLUDE_DIRS "."
    REQUIRES dsp driver fatfs sdmmc esp_timer
)
