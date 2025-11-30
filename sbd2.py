import pickle
import os
from typing import List, Tuple, Optional
from dataclasses import dataclass
import random

# Statystyki operacji
class Stats:
    def __init__(self):
        self.reads = 0
        self.writes = 0
    
    def reset(self):
        self.reads = 0
        self.writes = 0
    
    def __str__(self):
        return f"Odczyty: {self.reads}, Zapisy: {self.writes}"

stats = Stats()

@dataclass
class Record:
    """Rekord zawierający klucz i dane (zbiór liczb)"""
    key: int
    numbers: List[int]
    
    def get_sum(self):
        """Suma liczb - poprzednie kryterium sortowania"""
        return sum(self.numbers)
    
    def __str__(self):
        return f"[Key={self.key}, Numbers={self.numbers}, Sum={self.get_sum()}]"

class BTreeNode:
    """Węzeł B-drzewa"""
    def __init__(self, is_leaf=True):
        self.keys = []  # Lista kluczy
        self.addresses = []  # Lista adresów rekordów w pliku głównym
        self.children = []  # Lista wskaźników do dzieci (adresów stron)
        self.is_leaf = is_leaf
        self.parent_addr = None  # Adres rodzica (dla ułatwienia operacji)
    
    def is_full(self, max_keys):
        return len(self.keys) >= max_keys
    
    def is_underflow(self, min_keys):
        return len(self.keys) < min_keys

class BTree:
    """Implementacja B-drzewa"""
    def __init__(self, filename="btree_data.db", d=2):
        self.filename = filename
        self.index_filename = filename + ".idx"
        self.free_pages_filename = filename + ".free"
        self.d = d  # Stopień drzewa
        self.max_keys = 2 * d
        self.min_keys = d
        self.root_addr = None
        self.next_page_addr = 0  # Następny wolny adres strony
        self.free_pages = []  # Lista zwolnionych stron do ponownego użycia
        
        # Inicjalizacja plików
        self._init_files()
    
    def _init_files(self):
        """Inicjalizacja plików bazy danych"""
        if not os.path.exists(self.filename):
            with open(self.filename, 'wb') as f:
                pass
        if not os.path.exists(self.index_filename):
            with open(self.index_filename, 'wb') as f:
                pass
        if not os.path.exists(self.free_pages_filename):
            self.free_pages = []
            self._save_free_pages()
        else:
            self._load_free_pages()
    
    def _save_free_pages(self):
        """Zapisz listę wolnych stron"""
        with open(self.free_pages_filename, 'wb') as f:
            pickle.dump(self.free_pages, f)
        stats.writes += 1
    
    def _load_free_pages(self):
        """Wczytaj listę wolnych stron"""
        with open(self.free_pages_filename, 'rb') as f:
            self.free_pages = pickle.load(f)
        stats.reads += 1
    
    def _get_new_page_addr(self):
        """Pobierz adres dla nowej strony (z puli wolnych lub nowy)"""
        if self.free_pages:
            return self.free_pages.pop()
        else:
            addr = self.next_page_addr
            self.next_page_addr += 1
            return addr
    
    def _free_page_addr(self, addr):
        """Zwolnij adres strony do ponownego użycia"""
        self.free_pages.append(addr)
        self._save_free_pages()
    
    def _write_node(self, addr, node):
        """Zapisz węzeł do pliku indeksu"""
        with open(self.index_filename, 'r+b') as f:
            f.seek(addr * 4096)  # Zakładamy strony po 4KB
            pickle.dump(node, f)
        stats.writes += 1
    
    def _read_node(self, addr):
        """Odczytaj węzeł z pliku indeksu"""
        with open(self.index_filename, 'rb') as f:
            f.seek(addr * 4096)
            node = pickle.load(f)
        stats.reads += 1
        return node
    
    def _write_record(self, addr, record):
        """Zapisz rekord do pliku głównego"""
        with open(self.filename, 'r+b') as f:
            f.seek(addr * 1024)  # Zakładamy rekordy po 1KB
            pickle.dump(record, f)
        stats.writes += 1
    
    def _read_record(self, addr):
        """Odczytaj rekord z pliku głównego"""
        with open(self.filename, 'rb') as f:
            f.seek(addr * 1024)
            record = pickle.load(f)
        stats.reads += 1
        return record
    
    def search(self, key):
        """Wyszukaj rekord po kluczu"""
        if self.root_addr is None:
            return None
        
        return self._search_recursive(self.root_addr, key)
    
    def _search_recursive(self, node_addr, key):
        """Rekurencyjne wyszukiwanie w B-drzewie"""
        node = self._read_node(node_addr)
        
        # Szukaj klucza w węźle
        i = 0
        while i < len(node.keys) and key > node.keys[i]:
            i += 1
        
        # Znaleziono klucz
        if i < len(node.keys) and key == node.keys[i]:
            record_addr = node.addresses[i]
            return self._read_record(record_addr)
        
        # Jeśli liść, klucz nie istnieje
        if node.is_leaf:
            return None
        
        # Szukaj w odpowiednim dziecku
        return self._search_recursive(node.children[i], key)
    
    def insert(self, record):
        """Wstaw rekord do B-drzewa"""
        # Sprawdź czy klucz już istnieje
        if self.search(record.key) is not None:
            print(f"Błąd: Klucz {record.key} już istnieje!")
            return False
        
        # Zapisz rekord do pliku głównego
        record_addr = self._get_new_page_addr()
        with open(self.filename, 'ab') as f:
            f.seek(record_addr * 1024)
            pickle.dump(record, f)
        stats.writes += 1
        
        # Jeśli drzewo puste, utwórz korzeń
        if self.root_addr is None:
            root = BTreeNode(is_leaf=True)
            root.keys.append(record.key)
            root.addresses.append(record_addr)
            self.root_addr = self._get_new_page_addr()
            self._write_node(self.root_addr, root)
            return True
        
        # Wstaw do istniejącego drzewa
        self._insert_recursive(self.root_addr, record.key, record_addr)
        return True
    
    def _insert_recursive(self, node_addr, key, record_addr):
        """Rekurencyjne wstawianie do B-drzewa"""
        node = self._read_node(node_addr)
        
        # Znajdź pozycję dla klucza
        i = 0
        while i < len(node.keys) and key > node.keys[i]:
            i += 1
        
        if node.is_leaf:
            # Wstaw do liścia
            node.keys.insert(i, key)
            node.addresses.insert(i, record_addr)
            self._write_node(node_addr, node)
            
            # Sprawdź przepełnienie
            if len(node.keys) > self.max_keys:
                self._handle_overflow(node_addr)
        else:
            # Wstaw do odpowiedniego dziecka
            child_addr = node.children[i]
            self._insert_recursive(child_addr, key, record_addr)
    
    def _handle_overflow(self, node_addr):
        """Obsłuż przepełnienie węzła"""
        node = self._read_node(node_addr)
        
        # Spróbuj kompensacji
        if self._try_compensation(node_addr):
            return
        
        # Kompensacja niemożliwa - wykonaj podział
        self._split_node(node_addr)
    
    def _try_compensation(self, node_addr):
        """Spróbuj kompensacji z sąsiadem"""
        node = self._read_node(node_addr)
        
        if node.parent_addr is None:
            return False
        
        parent = self._read_node(node.parent_addr)
        
        # Znajdź pozycję węzła w rodzicu
        node_idx = parent.children.index(node_addr)
        
        # Sprawdź lewego sąsiada
        if node_idx > 0:
            left_sibling_addr = parent.children[node_idx - 1]
            left_sibling = self._read_node(left_sibling_addr)
            
            if len(left_sibling.keys) < self.max_keys:
                # Kompensacja z lewym sąsiadem
                self._compensate_with_left(node_addr, left_sibling_addr, node.parent_addr, node_idx)
                return True
        
        # Sprawdź prawego sąsiada
        if node_idx < len(parent.children) - 1:
            right_sibling_addr = parent.children[node_idx + 1]
            right_sibling = self._read_node(right_sibling_addr)
            
            if len(right_sibling.keys) < self.max_keys:
                # Kompensacja z prawym sąsiadem
                self._compensate_with_right(node_addr, right_sibling_addr, node.parent_addr, node_idx)
                return True
        
        return False
    
    def _compensate_with_left(self, node_addr, left_addr, parent_addr, node_idx):
        """Kompensacja z lewym sąsiadem"""
        node = self._read_node(node_addr)
        left = self._read_node(left_addr)
        parent = self._read_node(parent_addr)
        
        # Zbierz wszystkie klucze
        all_keys = left.keys + [parent.keys[node_idx - 1]] + node.keys
        all_addrs = left.addresses + [None] + node.addresses  # None to separator
        
        if not node.is_leaf:
            all_children = left.children + node.children
        
        # Podziel równo
        mid = len(all_keys) // 2
        
        left.keys = all_keys[:mid]
        left.addresses = all_addrs[:mid]
        
        parent.keys[node_idx - 1] = all_keys[mid]
        
        node.keys = all_keys[mid + 1:]
        node.addresses = [a for a in all_addrs[mid + 1:] if a is not None]
        
        if not node.is_leaf:
            left.children = all_children[:mid + 1]
            node.children = all_children[mid + 1:]
        
        self._write_node(left_addr, left)
        self._write_node(node_addr, node)
        self._write_node(parent_addr, parent)
    
    def _compensate_with_right(self, node_addr, right_addr, parent_addr, node_idx):
        """Kompensacja z prawym sąsiadem"""
        node = self._read_node(node_addr)
        right = self._read_node(right_addr)
        parent = self._read_node(parent_addr)
        
        # Zbierz wszystkie klucze
        all_keys = node.keys + [parent.keys[node_idx]] + right.keys
        all_addrs = node.addresses + [None] + right.addresses
        
        if not node.is_leaf:
            all_children = node.children + right.children
        
        # Podziel równo
        mid = len(all_keys) // 2
        
        node.keys = all_keys[:mid]
        node.addresses = all_addrs[:mid]
        
        parent.keys[node_idx] = all_keys[mid]
        
        right.keys = all_keys[mid + 1:]
        right.addresses = [a for a in all_addrs[mid + 1:] if a is not None]
        
        if not node.is_leaf:
            node.children = all_children[:mid + 1]
            right.children = all_children[mid + 1:]
        
        self._write_node(node_addr, node)
        self._write_node(right_addr, right)
        self._write_node(parent_addr, parent)
    
    def _split_node(self, node_addr):
        """Podziel węzeł"""
        node = self._read_node(node_addr)
        
        mid = len(node.keys) // 2
        mid_key = node.keys[mid]
        
        # Utwórz nowy węzeł
        new_node = BTreeNode(is_leaf=node.is_leaf)
        new_node.keys = node.keys[mid + 1:]
        new_node.addresses = node.addresses[mid + 1:]
        
        if not node.is_leaf:
            new_node.children = node.children[mid + 1:]
        
        # Zaktualizuj stary węzeł
        node.keys = node.keys[:mid]
        node.addresses = node.addresses[:mid]
        
        if not node.is_leaf:
            node.children = node.children[:mid + 1]
        
        new_node_addr = self._get_new_page_addr()
        self._write_node(new_node_addr, new_node)
        self._write_node(node_addr, node)
        
        # Wstaw środkowy klucz do rodzica
        if node.parent_addr is None:
            # Utwórz nowy korzeń
            new_root = BTreeNode(is_leaf=False)
            new_root.keys.append(mid_key)
            new_root.addresses.append(node.addresses[mid])
            new_root.children.append(node_addr)
            new_root.children.append(new_node_addr)
            
            new_root_addr = self._get_new_page_addr()
            self.root_addr = new_root_addr
            
            node.parent_addr = new_root_addr
            new_node.parent_addr = new_root_addr
            
            self._write_node(new_root_addr, new_root)
            self._write_node(node_addr, node)
            self._write_node(new_node_addr, new_node)
        else:
            # Wstaw do istniejącego rodzica
            parent = self._read_node(node.parent_addr)
            
            idx = parent.children.index(node_addr)
            parent.keys.insert(idx, mid_key)
            parent.addresses.insert(idx, node.addresses[mid])
            parent.children.insert(idx + 1, new_node_addr)
            
            new_node.parent_addr = node.parent_addr
            
            self._write_node(node.parent_addr, parent)
            self._write_node(new_node_addr, new_node)
            
            if len(parent.keys) > self.max_keys:
                self._handle_overflow(node.parent_addr)
    
    def delete(self, key):
        """Usuń rekord po kluczu"""
        if self.root_addr is None:
            print(f"Błąd: Drzewo jest puste!")
            return False
        
        result = self._delete_recursive(self.root_addr, key)
        
        if result:
            # Sprawdź czy korzeń jest pusty
            root = self._read_node(self.root_addr)
            if len(root.keys) == 0 and not root.is_leaf:
                old_root_addr = self.root_addr
                self.root_addr = root.children[0]
                self._free_page_addr(old_root_addr)
        
        return result
    
    def _delete_recursive(self, node_addr, key):
        """Rekurencyjne usuwanie z B-drzewa"""
        node = self._read_node(node_addr)
        
        i = 0
        while i < len(node.keys) and key > node.keys[i]:
            i += 1
        
        if i < len(node.keys) and key == node.keys[i]:
            # Znaleziono klucz
            if node.is_leaf:
                # Usuń z liścia
                record_addr = node.addresses[i]
                self._free_page_addr(record_addr)
                
                node.keys.pop(i)
                node.addresses.pop(i)
                self._write_node(node_addr, node)
                
                # Sprawdź niedopełnienie
                if node_addr != self.root_addr and len(node.keys) < self.min_keys:
                    self._handle_underflow(node_addr)
                
                return True
            else:
                # Zastąp kluczem z poddrzewa
                # Znajdź największy klucz w lewym poddrzewie
                pred_key, pred_addr = self._get_predecessor(node.children[i])
                node.keys[i] = pred_key
                node.addresses[i] = pred_addr
                self._write_node(node_addr, node)
                
                # Usuń znaleziony klucz z liścia
                return self._delete_recursive(node.children[i], pred_key)
        elif not node.is_leaf:
            # Szukaj w dziecku
            return self._delete_recursive(node.children[i], key)
        else:
            print(f"Błąd: Klucz {key} nie istnieje!")
            return False
    
    def _get_predecessor(self, node_addr):
        """Znajdź poprzednika (największy klucz w poddrzewie)"""
        node = self._read_node(node_addr)
        
        if node.is_leaf:
            return node.keys[-1], node.addresses[-1]
        
        return self._get_predecessor(node.children[-1])
    
    def _handle_underflow(self, node_addr):
        """Obsłuż niedopełnienie węzła"""
        node = self._read_node(node_addr)
        parent = self._read_node(node.parent_addr)
        
        node_idx = parent.children.index(node_addr)
        
        # Spróbuj kompensacji z sąsiadami
        if node_idx > 0:
            left_addr = parent.children[node_idx - 1]
            left = self._read_node(left_addr)
            if len(left.keys) > self.min_keys:
                self._borrow_from_left(node_addr, left_addr, node.parent_addr, node_idx)
                return
        
        if node_idx < len(parent.children) - 1:
            right_addr = parent.children[node_idx + 1]
            right = self._read_node(right_addr)
            if len(right.keys) > self.min_keys:
                self._borrow_from_right(node_addr, right_addr, node.parent_addr, node_idx)
                return
        
        # Kompensacja niemożliwa - złącz węzły
        if node_idx > 0:
            left_addr = parent.children[node_idx - 1]
            self._merge_nodes(left_addr, node_addr, node.parent_addr, node_idx - 1)
        else:
            right_addr = parent.children[node_idx + 1]
            self._merge_nodes(node_addr, right_addr, node.parent_addr, node_idx)
    
    def _borrow_from_left(self, node_addr, left_addr, parent_addr, node_idx):
        """Pożycz klucz od lewego sąsiada"""
        node = self._read_node(node_addr)
        left = self._read_node(left_addr)
        parent = self._read_node(parent_addr)
        
        # Przenieś klucz z rodzica do węzła
        node.keys.insert(0, parent.keys[node_idx - 1])
        node.addresses.insert(0, parent.addresses[node_idx - 1])
        
        if not node.is_leaf:
            node.children.insert(0, left.children.pop())
        
        # Przenieś klucz z lewego sąsiada do rodzica
        parent.keys[node_idx - 1] = left.keys.pop()
        parent.addresses[node_idx - 1] = left.addresses.pop()
        
        self._write_node(node_addr, node)
        self._write_node(left_addr, left)
        self._write_node(parent_addr, parent)
    
    def _borrow_from_right(self, node_addr, right_addr, parent_addr, node_idx):
        """Pożycz klucz od prawego sąsiada"""
        node = self._read_node(node_addr)
        right = self._read_node(right_addr)
        parent = self._read_node(parent_addr)
        
        # Przenieś klucz z rodzica do węzła
        node.keys.append(parent.keys[node_idx])
        node.addresses.append(parent.addresses[node_idx])
        
        if not node.is_leaf:
            node.children.append(right.children.pop(0))
        
        # Przenieś klucz z prawego sąsiada do rodzica
        parent.keys[node_idx] = right.keys.pop(0)
        parent.addresses[node_idx] = right.addresses.pop(0)
        
        self._write_node(node_addr, node)
        self._write_node(right_addr, right)
        self._write_node(parent_addr, parent)
    
    def _merge_nodes(self, left_addr, right_addr, parent_addr, parent_idx):
        """Złącz dwa węzły"""
        left = self._read_node(left_addr)
        right = self._read_node(right_addr)
        parent = self._read_node(parent_addr)
        
        # Przenieś klucz z rodzica
        left.keys.append(parent.keys[parent_idx])
        left.addresses.append(parent.addresses[parent_idx])
        
        # Przenieś wszystko z prawego węzła
        left.keys.extend(right.keys)
        left.addresses.extend(right.addresses)
        
        if not left.is_leaf:
            left.children.extend(right.children)
        
        # Usuń klucz z rodzica
        parent.keys.pop(parent_idx)
        parent.addresses.pop(parent_idx)
        parent.children.pop(parent_idx + 1)
        
        self._write_node(left_addr, left)
        self._write_node(parent_addr, parent)
        self._free_page_addr(right_addr)
        
        # Sprawdź niedopełnienie rodzica
        if parent_addr != self.root_addr and len(parent.keys) < self.min_keys:
            self._handle_underflow(parent_addr)
    
    def update(self, key, new_numbers):
        """Aktualizuj rekord"""
        record = self.search(key)
        if record is None:
            print(f"Błąd: Klucz {key} nie istnieje!")
            return False
        
        record.numbers = new_numbers
        
        # Znajdź adres rekordu i zaktualizuj
        node_addr = self.root_addr
        while node_addr is not None:
            node = self._read_node(node_addr)
            
            i = 0
            while i < len(node.keys) and key > node.keys[i]:
                i += 1
            
            if i < len(node.keys) and key == node.keys[i]:
                self._write_record(node.addresses[i], record)
                return True
            
            if node.is_leaf:
                break
            
            node_addr = node.children[i]
        
        return False
    
    def traverse(self):
        """Przejdź przez całe drzewo w porządku rosnącym"""
        if self.root_addr is None:
            return []
        
        return self._traverse_recursive(self.root_addr)
    
    def _traverse_recursive(self, node_addr):
        """Rekurencyjne przechodzenie drzewa"""
        node = self._read_node(node_addr)
        result = []
        
        for i in range(len(node.keys)):
            if not node.is_leaf:
                result.extend(self._traverse_recursive(node.children[i]))
            
            record = self._read_record(node.addresses[i])
            result.append(record)
        
        if not node.is_leaf and node.children:
            result.extend(self._traverse_recursive(node.children[-1]))
        
        return result
    
    def display_tree(self):
        """Wyświetl strukturę drzewa"""
        if self.root_addr is None:
            print("Drzewo jest puste")
            return
        
        print(f"\n=== Struktura B-drzewa (d={self.d}) ===")
        self._display_node(self.root_addr, 0, "ROOT")
    
    def _display_node(self, node_addr, level, label):
        """Wyświetl węzeł drzewa"""
        node = self._read_node(node_addr)
        
        indent = "  " * level
        node_type = "LEAF" if node.is_leaf else "INTERNAL"
        print(f"{indent}{label} [Addr={node_addr}, Type={node_type}]:")
        print(f"{indent}  Keys: {node.keys}")
        print(f"{indent}  Count: {len(node.keys)}/{self.max_keys}")
        
        if not node.is_leaf:
            for i, child_addr in enumerate(node.children):
                self._display_node(child_addr, level + 1, f"Child-{i}")
    
    def display_data(self):
        """Wyświetl wszystkie dane w porządku rosnącym"""
        print("\n=== Zawartość pliku danych ===")
        records = self.traverse()
        if not records:
            print("Brak rekordów")
            return
        
        for record in records:
            print(f"  {record}")
        print(f"Łącznie rekordów: {len(records)}")


def run_interactive():
    """Tryb interaktywny"""
    print("=== System zarządzania B-drzewem ===")
    print("Wprowadź stopień drzewa (d):")
    
    try:
        d = int(input("d = "))
        if d < 2:
            print("Stopień musi być >= 2. Ustawiam d=2")
            d = 2
    except:
        print("Błąd! Ustawiam d=2")
        d = 2
    
    btree = BTree(d=d)
    
    while True:
        print("\n=== MENU ===")
        print("1. Wstaw rekord")
        print("2. Wyszukaj rekord")
        print("3. Usuń rekord")
        print("4. Aktualizuj rekord")
        print("5. Wyświetl wszystkie rekordy")
        print("6. Wyświetl strukturę drzewa")
        print("7. Wczytaj plik testowy")
        print("8. Przeprowadź eksperyment")
        print("9. Wyjście")
        
        choice = input("\nWybór: ").strip()
        
        if choice == '1':
            try:
                key = int(input("Klucz: "))
                numbers_str = input("Liczby (oddzielone spacją): ")
                numbers = [int(x) for x in numbers_str.split()]
                
                stats.reset()
                record = Record(key, numbers)
                if btree.insert(record):
                    print(f"✓ Rekord wstawiony. {stats}")
                    btree.display_tree()
            except Exception as e:
                print(f"Błąd: {e}")
        
        elif choice == '2':
            try:
                key = int(input("Klucz: "))
                stats.reset()
                record = btree.search(key)
                if record:
                    print(f"✓ Znaleziono: {record}")
                else:
                    print("✗ Nie znaleziono")
                print(stats)
            except Exception as e:
                print(f"Błąd: {e}")
        
        elif choice == '3':
            try:
                key = int(input("Klucz: "))
                stats.reset()
                if btree.delete(key):
                    print(f"✓ Rekord usunięty. {stats}")
                    btree.display_tree()
            except Exception as e:
                print(f"Błąd: {e}")
        
        elif choice == '4':
            try:
                key = int(input("Klucz: "))
                numbers_str = input("Nowe liczby (oddzielone spacją): ")
                numbers = [int(x) for x in numbers_str.split()]
                
                stats.reset()
                if btree.update(key, numbers):
                    print(f"✓ Rekord zaktualizowany. {stats}")
            except Exception as e:
                print(f"Błąd: {e}")
                
        elif choice == '5':
            # Wyświetl wszystkie rekordy
            try:
                stats.reset()
                btree.display_data()
                print(stats)
            except Exception as e:
                print(f"Błąd: {e}")

        elif choice == '6':
            # Wyświetl strukturę drzewa
            try:
                btree.display_tree()
            except Exception as e:
                print(f"Błąd: {e}")

        elif choice == '7':
            # Wczytaj plik testowy (format: key num1 num2 ... per line)
            try:
                path = input("Ścieżka do pliku testowego (domyślnie 'test.txt'): ").strip()
                if not path:
                    path = 'test.txt'
                if not os.path.exists(path):
                    print(f"Plik {path} nie istnieje")
                    continue

                inserted = 0
                stats.reset()
                with open(path, 'r', encoding='utf-8') as tf:
                    for line in tf:
                        line = line.strip()
                        if not line or line.startswith('#'):
                            continue
                        parts = line.split()
                        try:
                            key = int(parts[0])
                            numbers = [int(x) for x in parts[1:]]
                        except Exception:
                            print(f"Niepoprawny wiersz: {line}")
                            continue

                        rec = Record(key, numbers)
                        if btree.insert(rec):
                            inserted += 1

                print(f"Wczytano rekordów: {inserted}. {stats}")
                btree.display_tree()
            except Exception as e:
                print(f"Błąd: {e}")

        elif choice == '8':
            # Przeprowadź eksperyment - seria losowych operacji na nowym drzewie
            try:
                n = int(input("Ile rekordów wstawić? (np. 100): ").strip() or "100")
                max_val = int(input("Maksymalny klucz (np. 10000): ").strip() or "10000")
                numbers_per_record = int(input("Ile liczb w rekordzie? (np. 5): ").strip() or "5")

                # Użyj tymczasowych plików by nie kolidować z aktualnym drzewem
                exp_filename = f"btree_exp_{random.randint(1,1000000)}.db"
                exp_tree = BTree(filename=exp_filename, d=btree.d)
                keys = []

                # Wstawianie
                stats.reset()
                for i in range(n):
                    # losowy unikalny klucz
                    while True:
                        k = random.randint(1, max_val)
                        if k not in keys:
                            break
                    keys.append(k)
                    nums = [random.randint(0, 100) for _ in range(numbers_per_record)]
                    exp_tree.insert(Record(k, nums))

                inserted = len(keys)
                print(f"Wstawiono {inserted} rekordów. {stats}")

                # Wyszukiwanie - losowe 20% z wstawionych + kilka nieistniejących
                stats.reset()
                searches = 0
                for _ in range(max(1, inserted // 5)):
                    k = random.choice(keys)
                    _ = exp_tree.search(k)
                    searches += 1
                for _ in range(max(1, inserted // 10)):
                    _ = exp_tree.search(max_val + random.randint(1, 1000))
                    searches += 1
                print(f"Przeprowadzono {searches} wyszukiwań. {stats}")

                # Aktualizacje - zmień kilka rekordów
                stats.reset()
                updates = 0
                for _ in range(max(1, inserted // 10)):
                    k = random.choice(keys)
                    nums = [random.randint(0, 100) for _ in range(numbers_per_record)]
                    if exp_tree.update(k, nums):
                        updates += 1
                print(f"Przeprowadzono {updates} aktualizacji. {stats}")

                # Usuwanie - usuń kilka rekordów
                stats.reset()
                deletes = 0
                for _ in range(max(1, inserted // 10)):
                    if not keys:
                        break
                    k = keys.pop(random.randrange(len(keys)))
                    if exp_tree.delete(k):
                        deletes += 1
                print(f"Przeprowadzono {deletes} usunięć. {stats}")

                print("Eksperyment zakończony. Struktura drzewa eksperymentalnego:")
                exp_tree.display_tree()
            except Exception as e:
                print(f"Błąd: {e}")

        elif choice == '9':
            print("Koniec programu. Zapisuję stan i wychodzę...")
            break
        else:
            print("Nieprawidłowy wybór. Spróbuj ponownie.")

    # Koniec pętli interactive

if __name__ == '__main__':
    run_interactive()
