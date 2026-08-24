# user_spec 추출본 (에이전트 리뷰용)

> 원본: user_spec/user_spec.html 을 텍스트로 추출한 것. 표·코드 서식이 일부 뭉개져 있으나 내용은 전량 보존.
> 원본에 포함된 다이어그램(image.png) 설명: Application–Master–Slave 구조에서
> ① REPLICATION=OFF인 customers(PK customer_id)와 REPLICATION=ON인 orders(PK order_id, FK customer_id→customers)가 마스터에 존재,
> ② 복제 세트에 포함된 orders만 슬레이브로 복제됨, ③ Failover 후 애플리케이션이 슬레이브의 orders를 읽고/쓰는데,
> ④ orders.customer_id가 참조할 customers 테이블(데이터)이 슬레이브에 없음 — FK 참조 테이블이 복제 제외일 때의 문제 상황을 도식화.

## 리뷰 배경 (스펙 외부 컨텍스트)

- 기존 CUBRID HA는 PK 있는 테이블만 복제. HA 실행 중 PK 컬럼 속성 변경 시 복제 누락 + applylogdb 에러(fail_count 증가) + 마스터/슬레이브 데이터 불일치 문제가 실제 발생.
- MySQL식 "PK 없으면 전 컬럼을 키로 사용"은 성능 문제로 배제, PostgreSQL REPLICA IDENTITY 컨셉 일부 채용(RK = PK 또는 NOT NULL UNIQUE 중 엔진 선택).

---

사용자 스펙
사용자 스펙

1. 제약 사항
HA 모드 실행 시 복제 테이블은 복제를 위한 복제 키 (RK: Replication Key) 가 존재하지 않으면 HA모드를 실행 할 수 없다.

HA 모드는 “cubrid hb start” 로 큐브리드를 실행시킨 상태를 의미하며 나머지는 모두 싱글모드
복제 키는 큐브리드 엔진에 의해 Primary Key(이후 PK로 표기) 혹은 Not Null Unique Key(이후 UK로 표기)들 중 하나로 선택된다 

복제키는 다음 기준에 의해 결정된다
PK가 존재한다면 PK가 복제 키가 됨
PK가 없이 UK가 존재한다면 UK가 복제 키가 됨
UK가 여러개 존재한다면 큐브리드 엔진에 의해 이 중 하나가 선택된다(ex. 테이블내에 명시된 순서 중 가장 빠른 순서)
모든 DDL은 슬레이브로 복제되며 테이블의 REPLICATION 옵션은 데이터 복제 여부를 결정한다. REPLICATION OFF 로 인한 데이터 불일치는 책임지지 않는다(6. 뷰(VIEW)).
사용자는 추가된 옵션(2. 변경되거나 추가된 SQL)을 통해 복제 제외 테이블을 생성할 수 있으며, 복제 제외 테이블은 복제 키의 유무와 상관 없이 생성 가능하다. 단 HA 복제 대상에서는 제외된다.

2. 변경되거나 추가된 SQL
복제 대상 테이블 및 복제 제외 테이블을 구분하기위해 CREATE TABLE과 ALTER 
TABLE 시 다음 옵션을 제공한다.
REPLICATION={ON|OFF}
2-1. CREATE TABLE 옵션 추가
CREATE TABLE … REPLICATION 옵션은 복제 테이블 생성 여부를 설정한다.
ON: 복제 테이블
OFF: 복제 제외 테이블
이 옵션은 생략 가능하며 생략시 ON으로 자동으로 복제 테이블로 생성된다. 주의할 점은 복제 키가 없는 테이블은 싱글 모드에서만 생성 가능하고, HA 전환시 에러가 발생한다. 

REPLICATION = ON 
예시 1. CREATE TABLE을 통한 테이블 생성 예시. 복제키가 존재하는 복제 테이블.csql> CREATE TABLE repl_table_with_rk(
	a INT PRIMARY KEY,
	b INT NOT NULL UNIQUE,
	c INT
);

// 또는 
csql> CREATE TABLE repl_table_with_rk(
	a INT PRIMARY KEY,
	b INT NOT NULL UNIQUE,
	c INT
)REPLICATION = ON;
예시 2. CREATE TABLE 을 통한 테이블 생성 예시. 복제 키가 존재하지 않는 복제 테이블. 오직 싱글모드에서만 생성 가능.csql> CREATE TABLE repl_table_without_rk(
	a INT,
);
// 또는
csql> CREATE TABLE repl_table_without_rk(
	a INT,
)REPLICATION = ON;
REPLICATION = OFF
예시 3. CREATE TABLE 을 통한 테이블 생성 예시. 복제 제외 PK가 존재하지만 복제 제외 테이블로 생성 됨.csql> CREATE TABLE non_repl_table_with_rk(
	a INT PRIMARY KEY
)REPLICATION = OFF;
예시 4. CREATE TABLE 을 통한 테이블 생성 예시.  PK가 존재하지 않는 테이블을 생성하기위해선 복제 제외 테이블로 생성해야 함.  csql> CREATE TABLE non_repl_table_without_rk(
	a INT
)REPLICATION = OFF;

2-2. ALTER 옵션 및 SQL 추가
ALTER TABLE … REPLICATION 은 테이블을 복제 테이블 혹은 복제 제외 테이블로 변경한다. 단, HA 모드에서는 복제 제외 테이블이 복제 테이블로 변경될 수 없다.
예시 5. REPLICATION = ONcsql> ALTER TABLE tbl REPLICATION=ON;

ERROR
예시 6. REPLICATION = OFFcsql> ALTER TABLE tbl REPLICATION=OFF;

OK

HA 환경에서 PK를 복제키로 사용하던 중 다른 컬럼으로 변경해야한다면 다음 SQL문을 사용해 변경할 수 있다.
예시 7. Multiple ALTERcsql> ALTER TABLE tbl DROP CONSTRAINT ..., ADD CONSTRAINT ...;

2-3. REPLICATION 조회
사용자는 REPLICATION 정보를 조회할 수 있어야하며, 아래는 일부 예시를 보인다
예시 8. show create table table_namecsql> show create table tbl;

=== <Result of SELECT Command in Line 1> ===

  TABLE                 CREATE TABLE
============================================
  'dba.tbl'             'CREATE TABLE [tbl] ([a] INTEGER NOT NULL, [b] INTEGER,  CONSTRAINT [pk_tbl_a] PRIMARY KEY  (
[a])) REUSE_OID, COLLATE utf8_bin, REPLICATION ON'
예시 9. select * from db_classcsql> select * from db_class;

=== <Result of SELECT Command in Line 1> ===

<00064> class_name        : 'tbl'
        owner_name        : 'DBA'
        class_type        : 'CLASS'
        is_system_class   : 'NO'
        tde_algorithm     : 'NONE'
        partitioned       : 'NO'
        is_reuse_oid_class: 'YES'
        collation         : 'utf8_bin'
        comment           : NULL
        replication       : ON

3. Single 제약사항
제약은 없으나 “2. 변경되거나 추가된 SQL” 에서 추가된 모든 SQL 을 사용해 복제 대상 및 복제 제외 테이블을 생성할 수 있다. 싱글 모드에서 생성된 복제 키가 없는 테이블은 HA모드 전환 시 복제 키를 추가하거나 복제 제외 테이블로 변경할 수 있어야한다. 따라서 REPLICATION 옵션 사용은 싱글 모드에서도 가능하다.

4. HA 제약사항(운영 중)
HA 환경에서 마스터에서 수행된 DDL은 모두 슬레이브로 복제된다. 단, 복제 옵션이 ON인 경우의 데이터만 슬레이브로 복제되며, 이로인해 마스터와 슬레이브의 데이터는 불일치 될 수 있다.
HA 환경 복제 제외테이블은  “ALTER TABLE … REPLICATION=ON” 을 이용한 복제 테이블로 변경하는것 외의 모든 DDL을 사용할 수 있다. 반면 복제 대상의 경우 다음 DDL에 대한 제약 사항이 존재한다.
4-1. CREATE TABLE
HA 모드에서는 CREATE TABLE 시 복제키가 없는 복제 테이블을 생성할 수 없으며, 나머지 기능은 “2-1. CREATE TABLE 옵션 추가”와 동일하다. 
예시 10. 복제 테이블에는 반드시 복제 키 후보가 1개 이상 필요하다csql> CREATE TABLE repl_table_with_rk(
	a INT
); 

ERROR
4-2. ALTER TABLE
HA 모드에서 복제 테이블에는 하나 이상의 복제키 후보가 필요하며, 이로인해 다음 제약사항이 존재한다.
복제키는 큐브리드 엔진에 의해 결정되며, 사용자는 복제키를 직접 수정할 수 없다.
테이블에 하나의 복제키만 존재한다면 복제키를 수정하는 DDL이 제한되지만, 다른 복제키 후보가 함께 존재한다면 모든 DDL은 허용된다(단, 기존의 제약사항은 유지된다.)

복제키 후보가 1개인 경우(= 복제키) 제약사항은 다음과 같다. 

기존의 연산 결과와 동일한 경우 PK, UK를 비교하기위한 예시만 표기한다.
PK를 복제키로 사용하는 경우 
예시 11. PK 혹은 PK속성을 갖는 컬럼 추가: 하나의 테이블에는 여러 PK가 존재할 수 없다. (기존과 동일)// PK 추가
csql> ALTER TABLE table_name ADD CONSTRAINT PRIMARY KEY(b);
// PK 컬럼 추가
csql> ALTER TABLE table_name ADD COLUMN (b INT PRIMARY KEY);

ERROR: Primary key "pk_tbl_a" already defined for class "dba.tbl".
예시 12. DROP PK: HA 환경에서 PK가 복제키로 사용될 경우 이 PK 혹은 PK 컬럼은 삭제할 수 없다.// PK 삭제
csql> ALTER TABLE table_name DROP PRIMARY KEY;
// PK 컬럼 삭제
csql> ALTER TABLE table_name DROP COLUMN b;

ERROR
예시 13. PK 를 다른 컬럼으로 변경csql> ALTER TABLE table_name DROP CONSTRAINT PRIMARY KEY, 
ADD CONSTRAINT PRIMARY KEY(a);

OK

복제키를 PK에서 UK로 변경하는 경우, 테이블에 UK가 추가됨에 제약은 없으므로 UK 추가(ADD CONSTRAINT, PK 제거(DROP CONSTRAINT) 로 가이드 됨. 
UK 를 복제키로 사용하는 경우
예시 14. PK 추가: UK를 복제키로 사용하고 있는 테이블은 PK가 없으므로 추가 가능(기존과 동일)// PK 추가
csql> ALTER TABLE table_name ADD CONSTRAINT PRIMARY KEY(b);
// PK 컬럼 추가
csql> ALTER TABLE table_name ADD COLUMN (b INT PRIMARY KEY);

OK
예시 15. UNIQUE 제약 삭제: 복제 키로 사용중인 컬럼은 UNIQUE 제약을 삭제할 수 없음// UK 속성 삭제
csql> ALTER TABLE table_name DROP CONSTRAINT u_tbl_a;
// UK 컬럼 삭제
csql> ALTER TABLE table_name DROP COLUMN a;

ERROR
예시 16. DROP INDEX: 복제키 후보가 없다면 삭제 불가csql> DROP INDEX idx_id ON tbl;

ERROR

5. 외래키
사용자가 HA 모드에서 외래키를 포함한 테이블을 생성한다면 참조 테이블 역시 반드시 복제 대상 테이블이여야한다. 만약 참조 테이블이 복제 대상 테이블이 아니라면 다음과 같은 문제가 발생할 수 있다.
HA 실행 시 참조 테이블은 복제 대상이 아니므로 Slave로 복제되지 않고, 오직 외래키 테이블만 복제 됨
Failover 발생
어플리케이션에서 “orders” 데이터 접근
외래키로 참조할 “customers” 가 존재하지 않음

이러한 에러 상황을 막기위해 외래키 테이블에서 참조하는 모든 테이블은 복제 대상이여야한다. 또한 HA 모드 실행 시 외래키 테이블에서 참조하는 테이블의 상태도 확인해 복제 제외 테이블을 참조할 경우 에러를 출력할 수 있어야한다.

5-1. CRATE TABLE 예시
예시 17. 복제 테이블 참조 예시csql> CREATE TABLE customers(
	customer_id INT PRIMARY KEY,
	country INT
);

csql> CREATE TABLE orders(
	order_id INT PRIMARY KEY,
	customer_id INT,
	CONSTRAINT fk_customer_id FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
);

OK

예시 18. 복제 제외 테이블 참조 예시csql> CREATE TABLE non_repl_customers(
	customer_id INT PRIMARY KEY,
	country INT
)REPLICATION=OFF;

csql> CREATE TABLE orders(
	order_id INT PRIMARY KEY,
	customer_id INT,
	CONSTRAINT fk_customer_id FOREIGN KEY (customer_id) 
	REFERENCES non_repl_customers(customer_id)
);

ERROR

5-2. ALTER TABLE 예시
복제 테이블을 참조예시
 예시 19. 외래키 추가 csql> CREATE TABLE new_orders(
	order_id INT PRIMARY KEY,
	customer_id INT
);

// customers 는 예시 17의 테이블
csql> ALTER TABLE new_orders ADD CONSTRAINT FOREIGN KEY(customer_id) 
REFERENCES customers(customer_id);

OK
예시 20. 외래키 컬럼 추가csql> CREATE TABLE new_orders(
	order_id INT PRIMARY KEY
);

// customers 는 예시 17의 테이블
csql> ALTER TABLE new_orders ADD COLUMN 
(customer_id INT FOREIGN KEY REFERENCES customers(customer_id));

OK
예시 21. 복제 테이블을 참조하는 외래키 제거csql> ALTER TABLE new_orders DROP FOREIGN KEY (fk_new_orders_customer_id);

OK
예시 22. 복제 테이블을 참조하는 외래키 컬럼 제거csql> ALTER TABLE new_orders DROP COLUMN customer_id;

OK
복제 제외 테이블 참조 예시
외래키 추가 csql> CREATE TABLE new_orders(
	order_id INT PRIMARY KEY
);

// customers 는 예시 18의 테이블
csql> ALTER TABLE new_orders ADD CONSTRAINT FOREIGN KEY(order_id) 
REFERENCES non_repl_customers(customer_id);

ERROR
 예시 23. 외래키 컬럼 추가csql> CREATE TABLE new_orders(
	order_id INT PRIMARY KEY,
);

// customers 는 예시 18의 테이블
csql> ALTER TABLE new_orders ADD COLUMN 
(customer_id INT FOREIGN KEY REFERENCES non_repl_customers(customer_id));

ERROR
6. 뷰(VIEW)
HA 환경에서 수행된 모든 DDL이 슬레이브에 반영됨에 따라 Failover 후 뷰 사용에는 제약이 없다. 단, 복제 제외 테이블이 뷰에 포함되어 있을 경우, 복제 제외테이블에는 데이터가 존재하지 않아 수행의 결과는 두 노드가 일치하지 않는다. 이 부분에대해 큐브리드 복제 모듈은 책임지지 않는다.
7. HA 전환
HA 실행시 다음 사항을 제약사항을 확인하며, 제약사항 위반 시 에러와함께 파일 리스트를 출력한다
복제 테이블에 복제키가 존재하지 않는 경우
외래키를 포함하는 복제 테이블의 참조 테이블이 복제 대상이 아닌경우

이 경우 싱글모드에서 ALTER TABLE… 을 이용해 복제 키에 해당하는 제약을 추가하거나 복제 제외 대상으로 변경한 후 HA를 재시작해아한다

8. UNLOADDB & LOADDB
unload 시 복제 테이블의 여부를 함께 저장한다.
load시 복제 여부를 저장하는 변수에따라 복제 테이블 혹은 복제 제외 테이블로 생성된다
복제 테이블의 경우 큐브리드는 자동으로 RK를 할당한다.
복제 여부를 저장하는 변수가 설정되어 있지 않다면 복제 대상(Default)으로 간주한다.
특히 하위 버전에서 unload 한 데이터 파일에는 복제 여부를 저장하는 변수가 설정되어있지 않으므로 (싱글 모드에서) load 시 모두 복제 테이블로 설정된다.

9. SUMMARY 
REPLICATION 를 통해 복제 대상과 복제 제외를 구분할 수 있다
이 키워드는 싱글 이나 SA에서도 사용 가능
RK가 있는 테이블 역시 복제 제외대상이 될 수 있음
HA 모드에서 복제 대상 테이블은 반드시 RK가 하나 이상 존재해야한다
복제 대상인 외래키 테이블에서 참조하는 모든 테이블이 복제 대상이여야한다
HA 전환 시 복제 대상에 RK가 존재하지 않는다면 사용자는 싱글모드에서 재구성 후 HA모드로 전환해야한다.
UNLOADDB 시 복제 대상 여부를 함께 출력해야하며, 이를 포함하지 않는 테이블은 모두 복제 제외 테이블이다.

