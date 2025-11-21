window.dashExtensions = Object.assign({}, window.dashExtensions, {
    default: {
        function0: function(feature, latlng) {
            const color = feature.properties.color || 'grey';
            const marker = L.circleMarker(latlng, {
                radius: 16,
                fillColor: color,
                color: "#000",
                weight: 1,
                opacity: 1,
                fillOpacity: 0.8
            });
            if (feature.properties && feature.properties.name) {
                marker.bindTooltip(`${feature.properties.name} (${feature.properties.city})`);
            }
            return marker;
        }
    }
});