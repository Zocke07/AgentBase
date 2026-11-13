import { Icon, type IconSize } from "../../components/icons/Icon";
import { ICON_NAMES } from "../../components/icons/paths";

/**
 * Every vendored icon at the three sizes it is drawn at, and filled as the
 * rail's selected row draws it. The stroke is 1.5 px at each size.
 */

const SIZES: readonly IconSize[] = [16, 20, 24];

export function IconsPage() {
  return (
    <div className="wb-controls">
      <ul className="wb-icons">
        {ICON_NAMES.map((name) => (
          <li key={name} className="wb-icon">
            <span className="wb-icon__sizes">
              {SIZES.map((size) => (
                <Icon key={size} name={name} size={size} />
              ))}
              <Icon name={name} size={24} filled />
            </span>
            <span className="wb-icon__name">{name}</span>
          </li>
        ))}
      </ul>
      <p className="type-caption wb-type__muted">
        From Lucide (ISC licence), copied as shapes into components/icons/paths.ts. Sizes: 16, 20 and 24 px, then 24 px
        filled.
      </p>
    </div>
  );
}
