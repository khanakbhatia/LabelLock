import styles from './styles.module.css';

/** Maps readable component class names to their locally scoped CSS module names. */
export function classes(names: string): string {
  return names.split(' ').map(name => styles[name] ?? name).join(' ');
}
