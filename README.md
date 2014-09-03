# MySQL5.6の並列レプリケーションに関して

* [はじめに](#%E3%81%AF%E3%81%98%E3%82%81%E3%81%AB)
* [まとめ](#%E3%81%BE%E3%81%A8%E3%82%81)
* [調査](#%E8%AA%BF%E6%9F%BB)
  * [設定方法](#%E8%A8%AD%E5%AE%9A%E6%96%B9%E6%B3%95)
  * [設定パラメータに関して](#%E8%A8%AD%E5%AE%9A%E3%83%91%E3%83%A9%E3%83%A1%E3%83%BC%E3%82%BF%E3%81%AB%E9%96%A2%E3%81%97%E3%81%A6)
      * [slave_parallel_workers](#slave_parallel_workers)
      * [slave_checkpoint_period](#slave_checkpoint_period)
      * [slave_checkpoint_group](#slave_checkpoint_group)
      * [slave_pending_jobs_size_max](#slave_pending_jobs_size_max)
      * [slave_transaction_retries](#slave_transaction_retries)
  * [show slave status のみかた](#show-slave-status-%E3%81%AE%E3%81%BF%E3%81%8B%E3%81%9F)
      * [非並列時（slave_parallel_workers=0）の場合と違うところ](#%E9%9D%9E%E4%B8%A6%E5%88%97%E6%99%82%EF%BC%88slave_parallel_workers%3D0%EF%BC%89%E3%81%AE%E5%A0%B4%E5%90%88%E3%81%A8%E9%81%95%E3%81%86%E3%81%A8%E3%81%93%E3%82%8D)
  * [mysql.slave_worker_info に関して](#mysqlslave_worker_info-%E3%81%AB%E9%96%A2%E3%81%97%E3%81%A6)
  * [start slave until がサポートされていない](#start-slave-until-%E3%81%8C%E3%82%B5%E3%83%9D%E3%83%BC%E3%83%88%E3%81%95%E3%82%8C%E3%81%A6%E3%81%84%E3%81%AA%E3%81%84)
  * [ポジションの管理方法](#%E3%83%9D%E3%82%B8%E3%82%B7%E3%83%A7%E3%83%B3%E3%81%AE%E7%AE%A1%E7%90%86%E6%96%B9%E6%B3%95)
    * [relay_log_info_repository が `TABLE` の場合](#relay_log_info_repository-%E3%81%8C-%60table%60-%E3%81%AE%E5%A0%B4%E5%90%88)
    * [relay_log_info_repository が `FILE` の場合](#relay_log_info_repository-%E3%81%8C-%60file%60-%E3%81%AE%E5%A0%B4%E5%90%88)
  * [slave_parallel_workers を ON => OFF にした場合](#slave_parallel_workers-%E3%82%92-on-%3D%3E-off-%E3%81%AB%E3%81%97%E3%81%9F%E5%A0%B4%E5%90%88)
  * [SQL_THREAD が止まった場合の復旧方法](#sql_thread-%E3%81%8C%E6%AD%A2%E3%81%BE%E3%81%A3%E3%81%9F%E5%A0%B4%E5%90%88%E3%81%AE%E5%BE%A9%E6%97%A7%E6%96%B9%E6%B3%95)
* [参考サイト](#%E5%8F%82%E8%80%83%E3%82%B5%E3%82%A4%E3%83%88)

# はじめに

MySQL 5.6.3 より追加された「並列レプリケーション」に関する調査結果を記す。

# まとめ

複数のデータベースが存在し、それぞれが独立して更新されるという条件の場合に性能アップが見込めるので利用する価値がある。
運用する上での条件として各 SQL_THREAD の状態を取るために `relay_log.info` をテーブルにする必要がある（テーブルにしなくても動作するが、ポジション管理に関して未検証）。

必要な設定は以下の2つ

* `set global slave_parallel_workers=x`
  * 数字 x はデータベース数か CPU 数のうち少ないほうに合わせるのが妥当か
* `set global relay_log_info_repository='TABLE'`

運用する上では、

* レプリケーション全体を見る場合は今までどおり `show slave status¥G`
* 各 SQL_THREAD を見る場合は `select * from slave_worker_info¥G`

懸念事項として、不整合の検出ができない点や、国内/国外の情報量が少ないところがある。
また、検証中に気づいたがスレーブ側のメモリの利用量が増えるのでパラメータの調整を行う上で注意すること。
不整合を防ぐ手段としては、データベースごとにユーザーを分けるという方法も考えられる。

# 調査

各調査内容は MySQL 5.6.19 を対象としている。また、動作確認は Oracle 公式で配布しているバイナリを利用した環境で行っている。

## 設定方法

slave で `slave_parallel_workers` を設定する。オンラインで有効にする場合は、設定変更後に `sql_thread` を一度ストップ->スタートする必要がある。

``` console
root@slave[(none)]> show variables like 'slave_parallel_workers';
+------------------------+-------+
| Variable_name          | Value |
+------------------------+-------+
| slave_parallel_workers | 0     |
+------------------------+-------+
1 row in set (0.00 sec)

root@slave[mysql]> show variables like 'slave_checkpoint%';
+-------------------------+-------+
| Variable_name           | Value |
+-------------------------+-------+
| slave_checkpoint_group  | 512   |
| slave_checkpoint_period | 300   |
+-------------------------+-------+
2 rows in set (0.00 sec)

root@slave[(none)]> set global slave_parallel_workers=4;
Query OK, 0 rows affected (0.00 sec)

root@slave[(none)]> stop slave sql_thread;
Query OK, 0 rows affected (0.01 sec)

root@slave[(none)]> start slave sql_thread;
Query OK, 0 rows affected, 1 warning (0.08 sec)

root@slave[(none)]> show warnings;
+-------+------+-----------------------------------------------------------------------------------------------------------------------------------------------------------------------+
| Level | Code | Message                                                                                                                                                               |
+-------+------+-----------------------------------------------------------------------------------------------------------------------------------------------------------------------+
| Note  | 1753 | slave_transaction_retries is not supported in multi-threaded slave mode. In the event of a transient failure, the slave will not retry the transaction and will stop. |
+-------+------+-----------------------------------------------------------------------------------------------------------------------------------------------------------------------+
1 row in set (0.00 sec)

root@slave[mysql]> show variables like 'slave_parallel_workers';
+------------------------+-------+
| Variable_name          | Value |
+------------------------+-------+
| slave_parallel_workers | 4     |
+------------------------+-------+
1 row in set (0.00 sec)

root@slave[(none)]> show processlist;
+-----+-------------+-----------+------+---------+------+-----------------------------------------------------------------------------+------------------+
| Id  | User        | Host      | db   | Command | Time | State                                                                       | Info             |
+-----+-------------+-----------+------+---------+------+-----------------------------------------------------------------------------+------------------+
|  15 | system user |           | NULL | Connect |  296 | Waiting for master to send event                                            | NULL             |
|  16 | system user |           | NULL | Connect |   35 | Slave has read all relay log; waiting for the slave I/O thread to update it | NULL             |
|  17 | system user |           | NULL | Connect |  296 | Waiting for an event from Coordinator                                       | NULL             |
|  18 | system user |           | NULL | Connect |  296 | Waiting for an event from Coordinator                                       | NULL             |
|  19 | system user |           | NULL | Connect |   35 | Waiting for an event from Coordinator                                       | NULL             |
|  20 | system user |           | NULL | Connect |   35 | Waiting for an event from Coordinator                                       | NULL             |
| 237 | root        | localhost | NULL | Query   |    0 | init                                                                        | show processlist |
+-----+-------------+-----------+------+---------+------+-----------------------------------------------------------------------------+------------------+

# 並列実行時は以下の様な感じ

root@slave[(none)]> show processlist;
+-----+-------------+-----------+----------+---------+------+-----------------------------------------------------------------------------+------------------------------------------------------------------------------------------------------+
| Id  | User        | Host      | db       | Command | Time | State                                                                       | Info                                                                                                 |
+-----+-------------+-----------+----------+---------+------+-----------------------------------------------------------------------------+------------------------------------------------------------------------------------------------------+
|  15 | system user |           | NULL     | Connect |  259 | Waiting for master to send event                                            | NULL                                                                                                 |
|  16 | system user |           | NULL     | Connect |    0 | Slave has read all relay log; waiting for the slave I/O thread to update it | NULL                                                                                                 |
|  17 | system user |           | NULL     | Connect |  259 | Waiting for an event from Coordinator                                       | NULL                                                                                                 |
|  18 | system user |           | NULL     | Connect |  259 | Waiting for an event from Coordinator                                       | NULL                                                                                                 |
|  19 | system user |           | sbtest02 | Connect |    0 | freeing items                                                               | INSERT INTO sbtest1(k, c, pad) VALUES(50163, '69984174524-26012810054-36805143149-32310898208-682028 |
|  20 | system user |           | sbtest01 | Connect |    0 | update                                                                      | INSERT INTO sbtest1(k, c, pad) VALUES(49652, '46135589944-64208092384-90164596631-22360606373-609787 |
| 201 | root        | localhost | NULL     | Query   |    0 | init                                                                        | show processlist                                                                                     |
+-----+-------------+-----------+----------+---------+------+-----------------------------------------------------------------------------+------------------------------------------------------------------------------------------------------+
```

Percona の資料には `Requires table repository` とあったが、relay_log が table でなくてもエラーにならない。

start slave 実行時に以下のメッセージが Error_log に出力された（後述） %%FIXME%%

``` text
4656 [Warning] Slave SQL: If a crash happens this configuration does not guarantee that the relay log info will be consistent, Error_code: 0
```
 
## 設定パラメータに関して

[MySQL :: MySQL 5.6 Reference Manual :: 17.1.4.3 Replication Slave Options and Variables](http://dev.mysql.com/doc/refman/5.6/en/replication-options-slave.html#sysvar_slave_parallel_workers)

#### slave_parallel_workers

* 設定値は並列に動く "SQL" Thread 数
* デフォルトは 0、最大 1024


#### slave_checkpoint_period

* デフォルト 300(ms)
* 各 SQL_THREAD が `SHOW SLAVE STATUS` を更新するまでの最大ms
* slave_checkpoint_group と連動して動く。どちらかのチェックポイントに達するとリセットされる（タクシーの運賃計算みたいなもの？）


#### slave_checkpoint_group

* デフォルト 512(transactions)
* 各 SQL_THREAD が `SHOW SLAVE STATUS` を更新するまでの最大トランザクション数
* slave_checkpoint_period と連動して動く。どちらかのチェックポイントに達するとリセットされる（タクシーの運賃計算みたいなもの？）


#### slave_pending_jobs_size_max

* デフォルト 16777216(16MB)
* 各 SQL_THREAD が利用する最大メモリサイズ。
  * Master の `max_allowed_packet` より大きくすること
* 全体の使用メモリの計算では考慮すべき場所


#### slave_transaction_retries

* warning にある通り、`slave_parallel_workers` が有効の場合（1以上の場合）無視される。


## show slave status のみかた

#### 非並列時（slave_parallel_workers=0）の場合と違うところ

[MySQL :: MySQL 5.6 Reference Manual :: 13.7.5.35 SHOW SLAVE STATUS Syntax](http://dev.mysql.com/doc/refman/5.6/en/show-slave-status.html#Seconds_Behind_Master)

**Exec_Master_Log_Pos**

一番**遅れてる** SQL_THREAD の位置を表す

**Seconds_Behind_Master**

Exec_Master_Log_Pos を元に計算されているため、最新の Commit 位置が出るわけではないはず？（検証して見たが確証は得られず...）


## mysql.slave_worker_info に関して

各 SQL_THREAD の状態を見るためのテーブル。
`slave_parallel_workers` を 1 以上かつ `relay_log_info_repository` が TABLE の場合に利用することが出来る。

``` console
root@slave[mysql]> select * from mysql.slave_worker_info\G;
*************************** 1. row ***************************
                        Id: 1
            Relay_log_name:
             Relay_log_pos: 0
           Master_log_name:
            Master_log_pos: 0
 Checkpoint_relay_log_name:
  Checkpoint_relay_log_pos: 0
Checkpoint_master_log_name:
 Checkpoint_master_log_pos: 0
          Checkpoint_seqno: 0
     Checkpoint_group_size: 64
   Checkpoint_group_bitmap:
*************************** 2. row ***************************
                        Id: 2
            Relay_log_name:
             Relay_log_pos: 0
           Master_log_name:
            Master_log_pos: 0
 Checkpoint_relay_log_name:
  Checkpoint_relay_log_pos: 0
Checkpoint_master_log_name:
 Checkpoint_master_log_pos: 0
          Checkpoint_seqno: 0
     Checkpoint_group_size: 64
   Checkpoint_group_bitmap:
*************************** 3. row ***************************
                        Id: 3
            Relay_log_name:
             Relay_log_pos: 0
           Master_log_name:
            Master_log_pos: 0
 Checkpoint_relay_log_name:
  Checkpoint_relay_log_pos: 0
Checkpoint_master_log_name:
 Checkpoint_master_log_pos: 0
          Checkpoint_seqno: 0
     Checkpoint_group_size: 64
   Checkpoint_group_bitmap:
*************************** 4. row ***************************
                        Id: 4
            Relay_log_name:
             Relay_log_pos: 0
           Master_log_name:
            Master_log_pos: 0
 Checkpoint_relay_log_name:
  Checkpoint_relay_log_pos: 0
Checkpoint_master_log_name:
 Checkpoint_master_log_pos: 0
          Checkpoint_seqno: 0
     Checkpoint_group_size: 64
   Checkpoint_group_bitmap:
4 rows in set (0.00 sec)
```


## start slave until がサポートされていない

マニュアルにも書いてあるが、multi-threaded mode では `start slave until` がサポートされていない。

では、実際に試すとどのようになるのだろうか。

```console
root@slave[(none)]> show variables like 'slave_parallel_workers';
+------------------------+-------+
| Variable_name          | Value |
+------------------------+-------+
| slave_parallel_workers | 4     |
+------------------------+-------+
1 row in set (0.00 sec)

root@slave[(none)]> start slave until master_log_file='mysql-bin.000003',master_log_pos=24575681;
Query OK, 0 rows affected, 2 warnings (0.01 sec)
 
root@slave[(none)]> show warnings;
+-------+------+------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+
| Level | Code | Message     |
+-------+------+------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+
| Note  | 1278 | It is recommended to use --skip-slave-start when doing step-by-step replication with START SLAVE UNTIL; otherwise, you will get problems if you get an unexpected slave's mysqld restart |
| Note  | 1753 | UNTIL condtion is not supported in multi-threaded slave mode. Slave is started in the sequential execution mode.     |
+-------+------+------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+
```

multi-threaded はサポートされてないから、**sequential execution mode** で開始されてる模様。
この場合、`slave_parallel_workers=0` として SQL_THREAD が実行されている（rpl_slave.cc より）。

この `start slave` により、IO_THREAD は開始される。SQL_THREAD も指定したポジションまで実行される。

エラーログには以下の様なログがでる。

```text
12185 [Note] Slave I/O thread: connected to master 'repl@master:3306',replication started in log 'mysql-bin.000003' at position 24050684
12185 [Note] Slave SQL thread initialized, starting replication in log 'mysql-bin.000003' at position 24050684, relay log './relay-bin.000001' position: 4
12185 [Note] Slave SQL thread stopped because it reached its UNTIL position 24575681
```

これらから、サポートされてないが使えないわけではなく、モードが変わって実行されている模様。つまり、パフォーマンス以外では気にしなくていい。


## ポジションの管理方法
* 各 SQL_THREAD の実行しているポジションはどこで管理されているのか

### relay_log_info_repository が `TABLE` の場合

`mysql.slave_worker_info` テーブルに以下のように管理され、MySQL を停止した際もその続きから実行される。

```console
root@slave[(none)]> select * from mysql.slave_worker_info\G;
*************************** 1. row ***************************
~snip~
*************************** 2. row ***************************
                        Id: 2
            Relay_log_name: ./relay-bin.000004
             Relay_log_pos: 58232125
           Master_log_name: mysql-bin.000003
            Master_log_pos: 106332955
 Checkpoint_relay_log_name: ./relay-bin.000004
  Checkpoint_relay_log_pos: 34096095
Checkpoint_master_log_name: mysql-bin.000003
 Checkpoint_master_log_pos: 82196925
          Checkpoint_seqno: 49
     Checkpoint_group_size: 64
   Checkpoint_group_bitmap: 
*************************** 3. row ***************************
                        Id: 3
            Relay_log_name: ./relay-bin.000004
             Relay_log_pos: 24131431
           Master_log_name: mysql-bin.000003
            Master_log_pos: 72232261
 Checkpoint_relay_log_name: ./relay-bin.000004
  Checkpoint_relay_log_pos: 7343097
Checkpoint_master_log_name: mysql-bin.000003
 Checkpoint_master_log_pos: 55443927
          Checkpoint_seqno: 34
     Checkpoint_group_size: 64
   Checkpoint_group_bitmap: 
*************************** 4. row ***************************
                        Id: 4
            Relay_log_name: ./relay-bin.000004
             Relay_log_pos: 13112113
           Master_log_name: mysql-bin.000003
            Master_log_pos: 61212943
 Checkpoint_relay_log_name: ./relay-bin.000004
  Checkpoint_relay_log_pos: 283
Checkpoint_master_log_name: mysql-bin.000003
 Checkpoint_master_log_pos: 48101113
          Checkpoint_seqno: 26
     Checkpoint_group_size: 64
   Checkpoint_group_bitmap:
```

### relay_log_info_repository が `FILE` の場合

「slave_parallel_workers が 1以上」かつ「relay_log_info_repository が `TABLE`」の場合に以下の様なメッセージがエラーログにでる。

```text
10151 [Warning] Slave SQL: If a crash happens this configuration does not guarantee that the relay log info will be consistent, Error_code: 0
```

また、この設定で SQL_THREAD で処理している状態のまま MySQL を終了した場合以下の様なメッセージがでて処理が終了するまで待たされる。

```text
10151 [Warning] Slave SQL: Coordinator thread of multi-threaded slave is being stopped in the middle of assigning a group of events; deferring to exit until the group completion  ... , Error_code: 0
```

つまり、この設定の場合は通常どおり MySQL の Start/Stop は問題ないが、Crash した場合はデータが保証されない（タイミングによっては壊れる）。


## slave_parallel_workers を ON => OFF にした場合

`set global` で変更した場合、SQL_THREAD を繋ぎ直すまでは特に何も発生しない。エラーログも warning もでない。
SQL_THREAD を繋ぎ直したら反映される。その際の処理は relay_log_info_repository の設定よって違うが、挙動は上記の通り。


## SQL_THREAD が止まった場合の復旧方法

Slave に直接データを書込、Duplicate key で止めた場合に `show slave status` に以下の様なメッセージ

```
Last_SQL_Error: Worker 3 failed executing transaction '' at master log mysql-bin.000003, end_log_pos 415313849; Error 'Duplicate entry '1' for key 'PRIMARY'' on query. Default database: 'stest01'. Query: 'insert into aaa (`id`,`name`) values (1,'fizz')'
```

エラーログには以下の様なメッセージ

```
15063 [ERROR] Slave SQL: Worker 3 failed executing transaction '' at master log mysql-bin.000003, end_log_pos 415313849; Error 'Duplicate entry '1' for key 'PRIMARY'' on query. Default database: 'stest01'. Query: 'insert into aaa (`id`,`name`) values (1,'fizz')', Error_code: 1062
15063 [Warning] Slave SQL: ... The slave coordinator and worker threads are stopped, possibly leaving data in inconsistent state. A restart should restore consistency automatically, although using non-transactional storage for data or info tables or DDL queries could lead to problems. In such cases you have to examine your data (see documentation for details). Error_code: 1756
```

この場合、slave から該当データを delete して `start slave`。


`SQL_SLAVE_SKIP_COUNTER=n` はエラーもなく使えてしまうが期待通り skip されるとは限らない。

```
15063 [Note] 'SQL_SLAVE_SKIP_COUNTER=1' executed at relay_log_file='./relay-bin.000027', relay_log_pos='760', master_log_name='mysql-bin.000003', master_log_pos='415313637' and new position at relay_log_file='./relay-bin.000027', relay_log_pos='1003', master_log_name='mysql-bin.000003', master_log_pos='415313880'
```

基本的には multi-threaded じゃない場合と同じだが、SQL_SLAVE_SKIP_COUNTER は使えないと思ったほうがいい。


# 参考サイト

[日々の覚書: 噂どおりのslave_parallel_workers](http://yoku0825.blogspot.jp/2012/11/slaveparallelworkers.html)

> 3) パラレルじゃないレプリケーションならリトライできるエラーでも、

> 　SQL_THREADが止まった上にその更新は適用されず失われる。

> 　⇒スレーブ側でSELECT .. FOR UPDATEでロックしてlock wait timeout exceededにしたら、

> 　　SQL_THREADは止まったけどSTART SLAVEしてもその更新は適用されないままさっくり続きのRelay Logを待つ。

> 　　⇒START SLAVEするたびにWarningで`こういう動作になるよ！'って教えてくれるけど。

[mysql 5.6新機能slave_parallel_workersを設定する際の注意 - hironomiuの日記](http://hironomiu.hatenablog.com/entry/2012/03/31/153945)

[PARALLEL SLAVE in MySQL REPLICATION](http://andreithedolphin.blogspot.jp/2012/10/parallel-slave-in-mysql-replication.html)

[www.percona.com/live/mysql-conference-2014/sites/default/files/slides/Getting the Most out of 5.6.pdf](http://www.percona.com/live/mysql-conference-2014/sites/default/files/slides/Getting%20the%20Most%20out%20of%205.6.pdf)
  
