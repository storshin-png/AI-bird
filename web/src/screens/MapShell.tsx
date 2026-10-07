import { useEffect, useState } from "react";
import { MapContainer, TileLayer } from "react-leaflet";
import { loadSpecies, type Species } from "../species";

type MapShellProps = {
  onLeave: () => void;
};

function SpeciesSlot({ species }: { species: Species[] }) {
  if (species.length === 0) {
    return null;
  }

  return (
    <ul className="species">
      {species.map((item) => (
        <li key={item.common_name_ru}>{item.common_name_ru}</li>
      ))}
    </ul>
  );
}

export function MapShell({ onLeave }: MapShellProps) {
  const [species, setSpecies] = useState<Species[]>([]);

  useEffect(() => {
    let active = true;

    loadSpecies().then((list) => {
      if (active) {
        setSpecies(list);
      }
    });

    return () => {
      active = false;
    };
  }, []);

  return (
    <main className="map-screen">
      <header className="topbar">
        <p className="eyebrow">AI-bird</p>
        <h1>Карта</h1>
        <button type="button" onClick={onLeave}>
          Выйти
        </button>
      </header>
      <p className="empty-state">нет датчиков</p>
      <SpeciesSlot species={species} />
      <div className="map-area">
        <MapContainer center={[56, 60]} zoom={3} scrollWheelZoom>
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
        </MapContainer>
      </div>
    </main>
  );
}
